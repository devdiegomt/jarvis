import sys
import types
from pathlib import Path
from typing import Any

import pytest
import truststore

from jarvis import cli, speech
from jarvis.config import ConfigError, SpeechSettings, load_settings, load_speech_settings
from jarvis.speech import (
    SPOKEN_REST_TEXT,
    PiperSpeaker,
    SpeechDownloadError,
    SpeechError,
    SpeechUnavailableError,
    build_speaker,
    describe_speech,
    download_voice,
    spoken_text,
    voice_downloaded,
)

VOICE = "es_MX-ald-medium"

# --- Configuración ----------------------------------------------------------


def test_speech_defaults(isolated_config_dir: Path) -> None:
    speech_settings = load_settings({"ANTHROPIC_API_KEY": "sk-test"}).speech

    assert speech_settings.enabled and speech_settings.engine == "local"
    assert speech_settings.voice == VOICE
    assert speech_settings.voices_dir == isolated_config_dir / "voz" / "piper"


def test_speech_can_be_disabled_and_voice_changed() -> None:
    settings = load_speech_settings({"JARVIS_RESPUESTA_VOZ": "NO", "JARVIS_PIPER_VOZ": "es_AR-daniela-high"})

    assert not settings.enabled
    assert settings.voice == "es_AR-daniela-high"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JARVIS_RESPUESTA_VOZ", "elevenlabs"),
        ("JARVIS_PIPER_VOZ", "daniela"),
        ("JARVIS_PIPER_VOZ", "../es_MX-ald-medium"),
    ],
)
def test_invalid_speech_settings_fail(name: str, value: str) -> None:
    with pytest.raises(ConfigError, match=name):
        load_speech_settings({name: value})


# --- Texto que se lee -------------------------------------------------------


def test_spoken_text_skips_links_and_emojis() -> None:
    text = spoken_text("⏰ Tienes reunión a las 9 ✅. Detalles: https://meet.google.com/abc-def")

    assert text == "Tienes reunión a las 9. Detalles: (enlace)"


def test_long_replies_are_cut_at_a_sentence() -> None:
    text = spoken_text("Primera frase. Segunda frase bastante más larga.", limit=30)

    assert text == f"Primera frase. {SPOKEN_REST_TEXT}"


def test_encode_ogg_opus_makes_a_voice_note() -> None:
    pytest.importorskip("av")  # en la CI no se instala el grupo de voz
    import numpy as np

    pcm = (np.sin(np.arange(22050) / 10) * 8000).astype(np.int16).tobytes()

    audio = speech.encode_ogg_opus(pcm, 22050)

    assert audio.startswith(b"OggS") and b"OpusHead" in audio[:200]


# --- Piper ------------------------------------------------------------------


class Chunk:
    def __init__(self, data: bytes, sample_rate: int = 22050) -> None:
        self.audio_int16_bytes = data
        self.sample_rate = sample_rate


class FakeVoice:
    def __init__(self, chunks: list[Chunk] | None = None, error: Exception | None = None) -> None:
        self.chunks = chunks if chunks is not None else [Chunk(b"\x01\x00"), Chunk(b"\x02\x00")]
        self.error = error
        self.texts: list[str] = []

    def synthesize(self, text: str) -> Any:
        self.texts.append(text)
        if self.error:
            raise self.error
        return iter(self.chunks)


def downloaded_voice(voices_dir: Path, voice: str = VOICE) -> Path:
    voices_dir.mkdir(parents=True, exist_ok=True)
    (voices_dir / f"{voice}.onnx").write_bytes(b"onnx")
    (voices_dir / f"{voice}.onnx.json").write_text("{}")
    return voices_dir / f"{voice}.onnx"


@pytest.fixture
def encoded(monkeypatch: pytest.MonkeyPatch) -> list[tuple[bytes, int]]:
    """Sustituye la codificación OGG (PyAV no está en la CI) y registra lo que se codificó."""
    calls: list[tuple[bytes, int]] = []

    def fake_encode(pcm: bytes, sample_rate: int) -> bytes:
        calls.append((pcm, sample_rate))
        return b"OggS-falso"

    monkeypatch.setattr(speech, "encode_ogg_opus", fake_encode)
    return calls


def speaker(tmp_path: Path, voice: FakeVoice, installed: bool = True) -> tuple[PiperSpeaker, list[Path]]:
    loads: list[Path] = []

    def load(path: Path) -> FakeVoice:
        loads.append(path)
        return voice

    return PiperSpeaker(VOICE, tmp_path, load_voice=load, installed=lambda: installed), loads


def test_speaks_and_loads_the_voice_once(tmp_path: Path, encoded: list[tuple[bytes, int]]) -> None:
    model = downloaded_voice(tmp_path)
    voice = FakeVoice()
    piper, loads = speaker(tmp_path, voice)

    assert piper.speak("Hola 👋") == b"OggS-falso"
    piper.speak("Otra vez")

    assert loads == [model]
    assert voice.texts == ["Hola", "Otra vez"]
    assert encoded[0] == (b"\x01\x00\x02\x00", 22050)


def test_not_installed_explains_how_to_install(tmp_path: Path) -> None:
    downloaded_voice(tmp_path)
    piper, _ = speaker(tmp_path, FakeVoice(), installed=False)

    with pytest.raises(SpeechUnavailableError, match="uv sync"):
        piper.speak("Hola")


def test_missing_voice_explains_how_to_download_it(tmp_path: Path) -> None:
    piper, loads = speaker(tmp_path, FakeVoice())

    with pytest.raises(SpeechUnavailableError, match="preparar-voz"):
        piper.speak("Hola")
    assert loads == []


@pytest.mark.parametrize("voice", [FakeVoice(chunks=[]), FakeVoice(error=RuntimeError("onnx"))])
def test_synthesis_problems_are_speech_errors(tmp_path: Path, encoded: list, voice: FakeVoice) -> None:
    downloaded_voice(tmp_path)
    piper, _ = speaker(tmp_path, voice)

    with pytest.raises(SpeechError):
        piper.speak("Hola")


def test_build_speaker(tmp_path: Path) -> None:
    assert build_speaker(SpeechSettings("no", VOICE, tmp_path)) is None
    assert isinstance(build_speaker(SpeechSettings("local", VOICE, tmp_path)), PiperSpeaker)


@pytest.mark.parametrize(
    ("engine", "installed", "downloaded", "expected"),
    [
        ("no", True, True, "desactivadas"),
        ("local", False, True, "no instaladas"),
        ("local", True, False, f"falta descargar la voz «{VOICE}»"),
        ("local", True, True, f"activadas (Piper local, voz {VOICE})"),
    ],
)
def test_describe_speech(tmp_path: Path, engine: str, installed: bool, downloaded: bool, expected: str) -> None:
    if downloaded:
        downloaded_voice(tmp_path)

    assert expected in describe_speech(SpeechSettings(engine, VOICE, tmp_path), installed=lambda: installed)


# --- Descarga de la voz -----------------------------------------------------


@pytest.fixture
def fake_piper(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    """Sustituye `piper.download_voices` (no está en la CI) y registra las descargas."""
    record = types.SimpleNamespace(downloads=[], injected=None, error=None)

    def fake_download(voice: str, download_dir: Path) -> None:
        record.injected = sys.modules["ssl"].SSLContext is truststore.SSLContext
        (download_dir / f"{voice}.onnx").write_bytes(b"a medias")
        if record.error:
            raise record.error
        downloaded_voice(download_dir, voice)
        record.downloads.append((voice, download_dir))

    package = types.ModuleType("piper")
    module = types.ModuleType("piper.download_voices")
    module.download_voice = fake_download  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "piper", package)
    monkeypatch.setitem(sys.modules, "piper.download_voices", module)
    return record


def test_download_uses_the_system_trust_store_only_while_downloading(
    tmp_path: Path, fake_piper: types.SimpleNamespace
) -> None:
    import ssl

    path = download_voice(VOICE, tmp_path / "piper")

    assert path == tmp_path / "piper" / f"{VOICE}.onnx"
    assert voice_downloaded(tmp_path / "piper", VOICE)
    assert fake_piper.injected
    assert ssl.SSLContext is not truststore.SSLContext


def test_failed_download_leaves_no_partial_files(tmp_path: Path, fake_piper: types.SimpleNamespace) -> None:
    fake_piper.error = OSError("404")

    with pytest.raises(SpeechDownloadError, match="JARVIS_PIPER_VOZ"):
        download_voice(VOICE, tmp_path)
    assert not (tmp_path / f"{VOICE}.onnx").exists()


# --- Comando preparar-voz ---------------------------------------------------


def prepare(monkeypatch: pytest.MonkeyPatch, installed: bool = True) -> None:
    # Solo la voz: la transcripción se prueba en test_voice.py y "Hey JARVIS" en test_pc_voice.py.
    monkeypatch.setattr(cli, "read_env", lambda: {"JARVIS_TRANSCRIPCION": "no"})
    monkeypatch.setattr("jarvis.speech.piper_installed", lambda: installed)
    monkeypatch.setattr(cli, "_prepare_wake_word", lambda _wake: True)
    cli.main(["preparar-voz"])


def test_prepare_voice_downloads_the_piper_voice(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    isolated_config_dir: Path,
    fake_piper: types.SimpleNamespace,
) -> None:
    prepare(monkeypatch)

    assert fake_piper.downloads == [(VOICE, isolated_config_dir / "voz" / "piper")]
    assert "Voz guardada" in capsys.readouterr().out


def test_prepare_voice_skips_a_voice_already_downloaded(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    isolated_config_dir: Path,
    fake_piper: types.SimpleNamespace,
) -> None:
    downloaded_voice(isolated_config_dir / "voz" / "piper")

    prepare(monkeypatch)

    assert fake_piper.downloads == []
    assert "ya está descargada" in capsys.readouterr().out


def test_prepare_voice_without_piper(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        prepare(monkeypatch, installed=False)

    assert "uv sync" in capsys.readouterr().err


def test_preload_loads_the_voice_once_and_never_raises(tmp_path: Path, encoded: list) -> None:
    piper, loads = speaker(tmp_path, FakeVoice())
    piper.preload()  # sin voz descargada: no falla
    assert loads == []

    downloaded_voice(tmp_path)
    piper.preload()
    piper.speak("Hola")
    assert len(loads) == 1


def test_assistant_warm_up_preloads_whisper_and_piper(isolated_config_dir: Path) -> None:
    from datetime import UTC

    from jarvis.agenda import SampleCalendar
    from jarvis.assistant import build_assistant

    calls: list[str] = []
    assistant = build_assistant(load_settings({"ANTHROPIC_API_KEY": "sk-test"}), SampleCalendar(UTC))
    assistant.transcriber.preload = lambda: calls.append("whisper")  # type: ignore[union-attr]
    assistant.speaker.preload = lambda: calls.append("piper")  # type: ignore[union-attr]

    assistant.start_warm_up().join(timeout=5)

    assert calls == ["whisper", "piper"]
