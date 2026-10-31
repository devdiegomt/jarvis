import io
import urllib.error
from pathlib import Path
from typing import Any

import pytest
import truststore

from jarvis import azure_speech, cli
from jarvis.azure_speech import (
    OGG_FORMAT,
    PCM_FORMAT,
    AzureAuthError,
    AzureQuotaError,
    AzureSpeaker,
    http_post,
)
from jarvis.config import ConfigError, load_settings, load_speech_settings
from jarvis.speech import PiperSpeaker, SpeechError, SpeechUnavailableError, build_speaker, describe_speech

KEY = "clave-secreta-de-azure"
AZURE_ENV = {"JARVIS_RESPUESTA_VOZ": "azure", "AZURE_SPEECH_KEY": KEY, "AZURE_SPEECH_REGION": "EastUS"}

# --- Configuración ----------------------------------------------------------


def test_azure_settings_default_to_salome() -> None:
    speech = load_speech_settings(AZURE_ENV)

    assert speech.engine == "azure" and speech.enabled
    assert (speech.azure_region, speech.azure_voice) == ("eastus", "es-CO-SalomeNeural")
    assert KEY not in repr(speech)  # la clave nunca se muestra


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"AZURE_SPEECH_KEY": ""}, "AZURE_SPEECH_KEY"),
        ({"AZURE_SPEECH_REGION": "east us"}, "AZURE_SPEECH_REGION"),
        ({"AZURE_SPEECH_REGION": ""}, "AZURE_SPEECH_REGION"),
        ({"JARVIS_AZURE_VOZ": "Salomé"}, "JARVIS_AZURE_VOZ"),
    ],
)
def test_invalid_azure_settings_fail(env: dict[str, str], expected: str) -> None:
    with pytest.raises(ConfigError, match=expected):
        load_speech_settings({**AZURE_ENV, **env})


def test_azure_settings_are_ignored_with_piper() -> None:
    assert load_speech_settings({"JARVIS_RESPUESTA_VOZ": "local"}).azure_key == ""


# --- Voz --------------------------------------------------------------------


class FakeAzure:
    def __init__(self, error: Exception | None = None) -> None:
        self.requests: list[tuple[str, dict[str, str], str]] = []
        self.error = error

    def __call__(self, url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        self.requests.append((url, headers, body.decode("utf-8")))
        if self.error:
            raise self.error
        return b"OggS-azure" if headers["X-Microsoft-OutputFormat"] == OGG_FORMAT else b"\x01\x00\x02\x00"


class FakeFallback:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.texts: list[str] = []
        self.preloaded = False

    def speak(self, text: str) -> bytes:
        self.texts.append(text)
        if self.error:
            raise self.error
        return b"OggS-piper"

    def synthesize(self, text: str) -> tuple[bytes, int]:
        self.texts.append(text)
        return b"\x00\x00", 22050

    def preload(self) -> None:
        self.preloaded = True


def azure(call: FakeAzure, fallback: FakeFallback | None = None) -> AzureSpeaker:
    return AzureSpeaker(KEY, "eastus", "es-CO-SalomeNeural", fallback=fallback, call=call)  # type: ignore[arg-type]


def test_voice_note_for_telegram_comes_ready_from_azure() -> None:
    call = FakeAzure()

    audio = azure(call).speak("Tienes 2 reuniones <hoy> & mañana ✅")

    url, headers, ssml = call.requests[0]
    assert audio == b"OggS-azure"
    assert url == "https://eastus.tts.speech.microsoft.com/cognitiveservices/v1"
    assert headers["Ocp-Apim-Subscription-Key"] == KEY
    assert headers["X-Microsoft-OutputFormat"] == OGG_FORMAT
    assert ssml == (
        "<speak version='1.0' xml:lang='es-CO'><voice name='es-CO-SalomeNeural'>"
        "Tienes 2 reuniones &lt;hoy&gt; &amp; mañana</voice></speak>"
    )


def test_pc_speakers_get_pcm() -> None:
    call = FakeAzure()

    assert azure(call).synthesize("Hola") == (b"\x01\x00\x02\x00", 24000)
    assert call.requests[0][1]["X-Microsoft-OutputFormat"] == PCM_FORMAT


def test_piper_answers_when_azure_fails() -> None:
    fallback = FakeFallback()
    speaker = azure(FakeAzure(error=SpeechError("sin red")), fallback)

    assert speaker.speak("Hola") == b"OggS-piper"
    assert speaker.synthesize("Hola") == (b"\x00\x00", 22050)


def test_azure_error_wins_when_the_fallback_cannot_help() -> None:
    speaker = azure(FakeAzure(error=AzureAuthError("clave mala")), FakeFallback(SpeechUnavailableError("sin Piper")))

    with pytest.raises(AzureAuthError, match="clave mala"):
        speaker.speak("Hola")


def test_without_fallback_the_error_is_raised() -> None:
    with pytest.raises(SpeechError):
        azure(FakeAzure(error=SpeechError("sin red"))).speak("Hola")


def test_preload_prepares_the_fallback() -> None:
    fallback = FakeFallback()

    azure(FakeAzure(), fallback).preload()

    assert fallback.preloaded


def test_nothing_to_say_does_not_call_azure() -> None:
    call = FakeAzure()

    with pytest.raises(SpeechError):
        azure(call).speak("👍")
    assert call.requests == []


# --- HTTP -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "error_type", "unavailable"),
    [(401, AzureAuthError, True), (403, AzureAuthError, True), (429, AzureQuotaError, True), (500, SpeechError, False)],
)
def test_http_errors(monkeypatch: pytest.MonkeyPatch, code: int, error_type: type, unavailable: bool) -> None:
    def rejected(request: Any, timeout: float, context: Any) -> Any:
        raise urllib.error.HTTPError(request.full_url, code, "x", {}, io.BytesIO(b""))  # type: ignore[arg-type]

    monkeypatch.setattr(azure_speech.urllib.request, "urlopen", rejected)

    with pytest.raises(error_type) as excinfo:
        http_post("https://eastus.tts.speech.microsoft.com/x", {"Ocp-Apim-Subscription-Key": KEY}, b"", 5)
    assert KEY not in str(excinfo.value)
    assert isinstance(excinfo.value, SpeechUnavailableError) is unavailable


def test_network_errors_and_trust_store(monkeypatch: pytest.MonkeyPatch) -> None:
    contexts: list[Any] = []

    def offline(request: Any, timeout: float, context: Any) -> Any:
        contexts.append(context)
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(azure_speech.urllib.request, "urlopen", offline)

    with pytest.raises(SpeechError, match="No pude conectar con Azure"):
        http_post("https://eastus.tts.speech.microsoft.com/x", {}, b"", 5)
    assert isinstance(contexts[0], truststore.SSLContext)


# --- Arranque, estado y comandos ---------------------------------------------


def test_build_speaker_uses_azure_with_piper_as_fallback(isolated_config_dir: Path) -> None:
    speaker = build_speaker(load_speech_settings(AZURE_ENV))

    assert isinstance(speaker, AzureSpeaker)
    assert isinstance(speaker._fallback, PiperSpeaker)


@pytest.mark.parametrize(("downloaded", "expected"), [(True, "respaldo: Piper"), (False, "sin respaldo en el PC")])
def test_describe_azure_speech(isolated_config_dir: Path, downloaded: bool, expected: str) -> None:
    speech = load_speech_settings(AZURE_ENV)
    if downloaded:
        speech.voices_dir.mkdir(parents=True)
        (speech.voices_dir / f"{speech.voice}.onnx").write_bytes(b"x")
        (speech.voices_dir / f"{speech.voice}.onnx.json").write_text("{}")

    text = describe_speech(speech, installed=lambda: True)

    assert text.startswith("activadas (Azure, voz es-CO-SalomeNeural")
    assert expected in text


def test_hey_jarvis_does_not_need_piper_with_azure(isolated_config_dir: Path) -> None:
    from jarvis.wake_word import FEATURE_MODELS, WAKE_MODEL, wake_word_problem

    settings = load_settings({"ANTHROPIC_API_KEY": "sk-test", **AZURE_ENV})
    settings.wake_word.models_dir.mkdir(parents=True)
    for name in (WAKE_MODEL, *FEATURE_MODELS):
        (settings.wake_word.models_dir / name).write_bytes(b"x")
    whisper = settings.voice.models_dir / settings.voice.model
    whisper.mkdir(parents=True)
    (whisper / "model.bin").write_bytes(b"x")
    (whisper / "config.json").write_text("{}")

    assert wake_word_problem(settings, installed=lambda: True) is None


def test_try_voice_plays_azure_without_fallback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    played: list[int] = []
    call = FakeAzure()
    monkeypatch.setattr(cli, "read_env", lambda: AZURE_ENV)
    monkeypatch.setattr(azure_speech, "http_post", call)
    monkeypatch.setattr(
        "jarvis.pc_voice.SoundDeviceAudio",
        lambda: type("A", (), {"play": lambda _self, samples, rate: played.append(rate)})(),
    )

    cli.main(["probar-voz", "Hola Diego"])

    assert played == [24000]
    assert "Hola Diego" in call.requests[0][2]
    assert "Voz: Azure (voz es-CO-SalomeNeural)" in capsys.readouterr().out


def test_try_voice_shows_azure_errors(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "read_env", lambda: AZURE_ENV)
    monkeypatch.setattr(azure_speech, "http_post", FakeAzure(error=AzureAuthError("Azure rechazó la clave")))
    monkeypatch.setattr("jarvis.pc_voice.SoundDeviceAudio", lambda: None)

    with pytest.raises(SystemExit):
        cli.main(["probar-voz"])

    assert "Azure rechazó la clave" in capsys.readouterr().err
