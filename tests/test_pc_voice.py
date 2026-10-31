import io
import ssl
import wave
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import truststore

from anthropic_fakes import FakeClient, text_response, tool_response
from jarvis import cli, wake_word
from jarvis.agent import Agent
from jarvis.chat import ChannelError, ChatService, IncomingMessage
from jarvis.config import ConfigError, load_settings, load_wake_word_settings
from jarvis.memory import ConversationStore
from jarvis.pc_voice import (
    CONFIRM_SUFFIX,
    NOT_HEARD_TEXT,
    SENDER,
    PcVoiceChannel,
    WakeWordListener,
    chime_samples,
    record_request,
    start_pc_voice,
    to_wav,
)
from jarvis.speech import SpeechError
from jarvis.tools import Confirmer, Tool, ToolRegistry
from jarvis.voice import TranscriptionError
from jarvis.wake_word import (
    FEATURE_MODELS,
    FRAME_SAMPLES,
    WAKE_MODEL,
    OpenWakeWordDetector,
    WakeWordDownloadError,
    WakeWordUnavailableError,
    describe_wake_word,
    download_wake_models,
    wake_models_downloaded,
)

QUIET = np.zeros(FRAME_SAMPLES, dtype=np.int16)
LOUD = np.full(FRAME_SAMPLES, 3000, dtype=np.int16)
TRIGGER = np.full(FRAME_SAMPLES, 7, dtype=np.int16)  # el detector falso se activa con este bloque


def frames_for(seconds: float, frame: np.ndarray) -> list[np.ndarray]:
    return [frame] * round(seconds / 0.08)


# --- Configuración ----------------------------------------------------------


def test_wake_word_is_off_by_default(isolated_config_dir: Path) -> None:
    wake = load_settings({"ANTHROPIC_API_KEY": "sk-test"}).wake_word

    assert not wake.enabled
    assert wake.threshold == 0.5
    assert wake.models_dir == isolated_config_dir / "voz" / "activacion"


def test_wake_word_can_be_enabled_with_its_threshold() -> None:
    wake = load_wake_word_settings({"JARVIS_PALABRA_ACTIVACION": "Sí", "JARVIS_ACTIVACION_UMBRAL": "0,7"})

    assert wake.enabled and wake.threshold == 0.7


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JARVIS_PALABRA_ACTIVACION", "siempre"),
        ("JARVIS_ACTIVACION_UMBRAL", "1.5"),
        ("JARVIS_ACTIVACION_UMBRAL", "alto"),
    ],
)
def test_invalid_wake_word_settings_fail(name: str, value: str) -> None:
    with pytest.raises(ConfigError, match=name):
        load_wake_word_settings({name: value})


# --- Detector y modelos ------------------------------------------------------


def downloaded_models(models_dir: Path) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    for name in (WAKE_MODEL, *FEATURE_MODELS):
        (models_dir / name).write_bytes(b"onnx")
    return models_dir


class FakeModel:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.resets = 0

    def predict(self, _frame: Any) -> dict[str, float]:
        return {"hey_jarvis_v0.1": self.scores.pop(0)}

    def reset(self) -> None:
        self.resets += 1


def test_detector_uses_the_threshold(tmp_path: Path) -> None:
    model = FakeModel([0.2, 0.6])
    detector = OpenWakeWordDetector(downloaded_models(tmp_path), threshold=0.5, load_model=lambda _dir: model)

    assert [detector.process(QUIET), detector.process(QUIET)] == [False, True]
    detector.reset()
    assert model.resets == 1


def test_detector_needs_its_models(tmp_path: Path) -> None:
    with pytest.raises(WakeWordUnavailableError, match="preparar-voz"):
        OpenWakeWordDetector(tmp_path, threshold=0.5, load_model=lambda _dir: FakeModel([]))


def test_download_writes_every_model_and_skips_existing(tmp_path: Path) -> None:
    (tmp_path / WAKE_MODEL).write_bytes(b"ya estaba")
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url.rsplit("/", 1)[1])
        return b"modelo"

    download_wake_models(tmp_path, fetch=fetch)

    assert fetched == list(FEATURE_MODELS)
    assert wake_models_downloaded(tmp_path)
    assert (tmp_path / WAKE_MODEL).read_bytes() == b"ya estaba"


def test_failed_download_leaves_no_partial_file(tmp_path: Path) -> None:
    def fetch(_url: str) -> bytes:
        raise ssl.SSLCertVerificationError("self-signed certificate")

    with pytest.raises(WakeWordDownloadError, match="certificados"):
        download_wake_models(tmp_path, fetch=fetch)
    assert list(tmp_path.iterdir()) == []


def test_https_download_uses_the_system_trust_store(monkeypatch: pytest.MonkeyPatch) -> None:
    contexts: list[Any] = []

    def fake_urlopen(url: str, timeout: float, context: Any) -> Any:
        contexts.append(context)
        return io.BytesIO(b"datos")

    monkeypatch.setattr(wake_word.urllib.request, "urlopen", fake_urlopen)

    assert wake_word._https_get("https://github.com/x.onnx") == b"datos"
    assert isinstance(contexts[0], truststore.SSLContext)


def settings_with(env: dict[str, str]):  # type: ignore[no-untyped-def]
    return load_settings({"ANTHROPIC_API_KEY": "sk-test", "JARVIS_PALABRA_ACTIVACION": "si", **env})


@pytest.mark.parametrize(
    ("env", "installed", "downloaded", "expected"),
    [
        ({"JARVIS_PALABRA_ACTIVACION": "no"}, True, True, "desactivada"),
        ({"JARVIS_RESPUESTA_VOZ": "no"}, True, True, "necesita las respuestas con voz"),
        ({"JARVIS_TRANSCRIPCION": "no"}, True, True, "necesita la transcripción"),
        ({}, False, True, "no está instalada"),
        ({}, True, False, "faltan modelos de voz"),
        ({"JARVIS_ACTIVACION_UMBRAL": "0.6"}, True, True, "activa («Hey JARVIS», umbral 0.6)"),
    ],
)
def test_describe_wake_word(
    isolated_config_dir: Path, env: dict[str, str], installed: bool, downloaded: bool, expected: str
) -> None:
    settings = settings_with(env)
    if downloaded:
        all_voice_models(settings)

    assert expected in describe_wake_word(settings, installed=lambda: installed)


def test_wake_word_needs_whisper_and_piper_downloaded(isolated_config_dir: Path) -> None:
    settings = settings_with({})
    downloaded_models(settings.wake_word.models_dir)  # solo los de "Hey JARVIS"

    assert "faltan modelos de voz" in describe_wake_word(settings, installed=lambda: True)


def all_voice_models(settings) -> None:  # type: ignore[no-untyped-def]
    """Modelos de "Hey JARVIS", de Whisper y voz de Piper, como los deja `preparar-voz`."""
    downloaded_models(settings.wake_word.models_dir)
    whisper = settings.voice.models_dir / settings.voice.model
    whisper.mkdir(parents=True)
    (whisper / "model.bin").write_bytes(b"x")
    (whisper / "config.json").write_text("{}")
    settings.speech.voices_dir.mkdir(parents=True)
    (settings.speech.voices_dir / f"{settings.speech.voice}.onnx").write_bytes(b"x")
    (settings.speech.voices_dir / f"{settings.speech.voice}.onnx.json").write_text("{}")


# --- Grabación del pedido ---------------------------------------------------


def test_recording_stops_after_a_short_silence() -> None:
    audio_in = frames_for(0.4, QUIET) + frames_for(1.2, LOUD) + frames_for(2, QUIET) + frames_for(5, LOUD)
    frames = iter(audio_in)

    audio = record_request(frames, threshold=300)

    assert audio is not None
    used = 5 + 15 + 9  # antes de hablar + voz + el silencio que cierra el pedido (9 bloques, ~0,7 s)
    assert len(audio) == FRAME_SAMPLES * used
    assert len(list(frames)) == len(audio_in) - used  # el resto queda para seguir escuchando


def test_no_speech_gives_up_after_four_seconds() -> None:
    frames = iter(frames_for(10, QUIET))

    assert record_request(frames, threshold=300) is None
    assert len(list(frames)) == 125 - 50


def test_long_requests_are_cut_at_fifteen_seconds() -> None:
    audio = record_request(iter(frames_for(30, LOUD)), threshold=300)

    assert audio is not None and len(audio) == FRAME_SAMPLES * round(15 / 0.08)


def test_wav_is_built_in_memory() -> None:
    with wave.open(io.BytesIO(to_wav(np.concatenate([LOUD, QUIET])))) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getnframes()) == (16000, 1, 2 * FRAME_SAMPLES)


def test_chime_is_short_and_not_too_loud() -> None:
    chime = chime_samples()

    assert chime.dtype == np.int16 and len(chime) < 16000 * 0.3 and np.abs(chime).max() <= 6000


# --- Canal del PC -----------------------------------------------------------


class FakeAudio:
    def __init__(self, frames: list[np.ndarray] | None = None) -> None:
        self._frames = frames or []
        self.played: list[tuple[int, int]] = []  # (muestras, frecuencia)
        self.flushes = 0
        self.speaking_seen: list[bool] = []
        self.channel: PcVoiceChannel | None = None

    def frames(self) -> Iterator[np.ndarray]:
        yield from self._frames

    def flush(self) -> None:
        self.flushes += 1

    def play(self, samples: np.ndarray, sample_rate: int) -> None:
        if self.channel is not None:
            self.speaking_seen.append(self.channel.speaking.is_set())
        self.played.append((len(samples), sample_rate))


class FakeSpeaker:
    def __init__(self, error: Exception | None = None) -> None:
        self.texts: list[str] = []
        self.error = error

    def synthesize(self, text: str) -> tuple[bytes, int]:
        self.texts.append(text)
        if self.error:
            raise self.error
        return b"\x01\x00" * 100, 22050


def channel_with(audio: FakeAudio | None = None, speaker: FakeSpeaker | None = None) -> PcVoiceChannel:
    audio = audio or FakeAudio()
    channel = PcVoiceChannel(speaker or FakeSpeaker(), audio, sleep=lambda _s: None)
    audio.channel = channel
    return channel


def test_channel_speaks_replies_and_mutes_the_microphone_meanwhile() -> None:
    audio, speaker = FakeAudio(), FakeSpeaker()
    channel = channel_with(audio, speaker)

    channel.send_text(SENDER, "Tienes dos reuniones.")

    assert speaker.texts == ["Tienes dos reuniones."]
    assert audio.played == [(100, 22050)]
    assert audio.speaking_seen == [True]
    assert not channel.speaking.is_set()


def test_confirmations_are_asked_aloud_and_wait_for_the_answer() -> None:
    speaker = FakeSpeaker()
    channel = channel_with(speaker=speaker)

    channel.send_with_buttons(SENDER, "Voy a avisar a Ana.", [("✅ Sí", "x:si"), ("❌ No", "x:no")])

    assert speaker.texts == [f"Voy a avisar a Ana. {CONFIRM_SUFFIX}"]
    assert channel.expecting_answer.is_set()


def test_speech_errors_become_channel_errors() -> None:
    channel = channel_with(speaker=FakeSpeaker(SpeechError("sin voz")))

    with pytest.raises(ChannelError, match="sin voz"):
        channel.send_text(SENDER, "Hola")
    assert not channel.speaking.is_set()


# --- Escucha ----------------------------------------------------------------


class FakeDetector:
    def __init__(self) -> None:
        self.processed = 0
        self.resets = 0

    def process(self, frame: np.ndarray) -> bool:
        self.processed += 1
        return frame is TRIGGER

    def reset(self) -> None:
        self.resets += 1


class FakeTranscriber:
    name = "prueba"

    def __init__(self, texts: list[str] | None = None, error: Exception | None = None) -> None:
        self.texts = texts or []
        self.error = error
        self.audios: list[bytes] = []

    def transcribe(self, audio: bytes) -> str:
        self.audios.append(audio)
        if self.error:
            raise self.error
        return self.texts.pop(0) if self.texts else ""


def listen(  # type: ignore[no-untyped-def]
    frames: list[np.ndarray], transcriber: FakeTranscriber, channel: PcVoiceChannel | None = None
):
    audio = FakeAudio(frames)
    channel = channel or channel_with(audio)
    audio.channel = channel
    submitted: list[IncomingMessage] = []
    detector = FakeDetector()
    WakeWordListener(audio, detector, channel, transcriber, submitted.append).run_forever()  # type: ignore[arg-type]
    return submitted, audio, detector


def test_activation_records_transcribes_and_submits_the_request() -> None:
    frames = frames_for(1, QUIET) + [TRIGGER] + frames_for(1, LOUD) + frames_for(1.2, QUIET)
    transcriber = FakeTranscriber(["¿Qué tengo hoy?"])

    submitted, audio, detector = listen(frames, transcriber)

    assert [(m.sender, m.text, m.transcribed) for m in submitted] == [(SENDER, "¿Qué tengo hoy?", True)]
    assert audio.played[0][1] == 16000  # el tono de activación
    assert transcriber.audios[0].startswith(b"RIFF")
    assert detector.resets >= 1
    assert audio.flushes == 0  # lo dicho mientras sonaba el tono es parte del pedido


@pytest.mark.parametrize(
    ("after_trigger", "transcriber"),
    [
        (frames_for(5, QUIET), FakeTranscriber(["no se usa"])),  # nadie habló
        (frames_for(1, LOUD) + frames_for(1.2, QUIET), FakeTranscriber([""])),  # Whisper no entendió nada
    ],
)
def test_nothing_heard_is_said_aloud(after_trigger: list[np.ndarray], transcriber: FakeTranscriber) -> None:
    speaker = FakeSpeaker()
    audio = FakeAudio()
    channel = channel_with(audio, speaker)

    submitted, _audio, _detector = listen([TRIGGER] + after_trigger, transcriber, channel)

    assert submitted == []
    assert speaker.texts == [NOT_HEARD_TEXT]


def test_transcription_errors_are_said_aloud() -> None:
    speaker = FakeSpeaker()
    channel = channel_with(FakeAudio(), speaker)
    transcriber = FakeTranscriber(error=TranscriptionError("Falta el modelo de voz."))

    listen([TRIGGER] + frames_for(1, LOUD) + frames_for(1.2, QUIET), transcriber, channel)

    assert speaker.texts == ["Falta el modelo de voz."]


def test_microphone_is_ignored_while_jarvis_speaks() -> None:
    channel = channel_with()
    channel.speaking.set()

    submitted, _audio, detector = listen([TRIGGER] * 5, FakeTranscriber(["hola"]), channel)

    assert submitted == [] and detector.processed == 0


def test_answer_to_a_confirmation_needs_no_wake_word() -> None:
    channel = channel_with()
    channel.expecting_answer.set()

    submitted, _audio, _detector = listen(frames_for(0.5, LOUD) + frames_for(1.2, QUIET), FakeTranscriber(["Sí."]), channel)

    assert [m.text for m in submitted] == ["Sí."]
    assert not channel.expecting_answer.is_set()


def test_silence_after_a_confirmation_cancels_it() -> None:
    speaker = FakeSpeaker()
    channel = channel_with(FakeAudio(), speaker)
    channel.expecting_answer.set()

    submitted, _audio, _detector = listen(frames_for(9, QUIET), FakeTranscriber(), channel)

    assert [(m.text, m.transcribed) for m in submitted] == [("no", False)]
    assert speaker.texts == ["No te escuché. ¿Sí o no?"]


# --- Con el chat ------------------------------------------------------------


def test_voice_conversation_with_a_confirmation(tmp_path: Path) -> None:
    speaker = FakeSpeaker()
    channel = channel_with(FakeAudio(), speaker)
    actions: list[str] = []
    anthropic = FakeClient([tool_response(("t1", "accion", {"texto": "avisar a Ana"})), text_response("Listo, le avisé.")])

    def agent_factory(history: list, system_prompt: str, confirm: Confirmer) -> Agent:
        registry = ToolRegistry(confirm=confirm)
        registry.register(
            Tool(
                name="accion",
                description="Acción con efectos externos.",
                input_schema={"type": "object", "properties": {"texto": {"type": "string"}}, "required": ["texto"]},
                func=lambda texto: actions.append(texto) or "hecho",
                confirmation_prompt=lambda tool_input: f"Voy a {tool_input['texto']}.",
            )
        )
        return Agent(
            client=anthropic,  # type: ignore[arg-type]
            registry=registry,
            model="m",
            system_prompt=system_prompt,
            history=history,
        )

    now = lambda: datetime(2026, 10, 31, 9, 0, tzinfo=UTC)  # noqa: E731
    chat = ChatService(
        channel=channel,
        store=ConversationStore(tmp_path / "jarvis.db", now=now),
        agent_factory=agent_factory,
        system_prompt=lambda: "Hablas por voz en el PC.",
        now=now,
    )
    chat.submit(IncomingMessage("pc:1", SENDER, "Avisa a Ana", transcribed=True))
    chat.submit(IncomingMessage("pc:2", SENDER, "Sí.", transcribed=True))  # lo que el micrófono oiría después
    chat.process_next(timeout=0)

    assert actions == ["avisar a Ana"]
    assert speaker.texts == [f"Voy a avisar a Ana. {CONFIRM_SUFFIX}", "Listo, le avisé."]
    first = anthropic.messages.calls[0]["messages"][0]["content"][0]["text"]
    assert first == "[2026-10-31 09:00] (nota de voz) Avisa a Ana"


# --- Arranque y comandos ----------------------------------------------------


def test_start_pc_voice_reports_what_is_missing(
    isolated_config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from jarvis.agenda import SampleCalendar
    from jarvis.assistant import build_assistant

    settings = settings_with({"JARVIS_RESPUESTA_VOZ": "no"})

    assert start_pc_voice(build_assistant(settings, SampleCalendar(UTC)), console=True) is None
    assert "necesita las respuestas con voz" in capsys.readouterr().out


def test_start_pc_voice_runs_the_listener_in_a_thread(
    isolated_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jarvis.agenda import SampleCalendar
    from jarvis.assistant import build_assistant

    monkeypatch.setattr("jarvis.pc_voice.wake_word_problem", lambda _settings: None)
    audio, detector = FakeAudio(frames_for(1, QUIET)), FakeDetector()

    thread = start_pc_voice(
        build_assistant(settings_with({}), SampleCalendar(UTC)), console=False, audio=audio, detector=detector
    )

    assert thread is not None
    thread.join(timeout=5)
    assert detector.processed == 12  # escuchó todo el audio y terminó


def test_prepare_voice_downloads_the_wake_word_models(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], isolated_config_dir: Path
) -> None:
    downloads: list[Path] = []
    monkeypatch.setattr(cli, "read_env", lambda: {"JARVIS_TRANSCRIPCION": "no"})
    monkeypatch.setattr(cli, "_prepare_speech", lambda _speech: True)
    monkeypatch.setattr("jarvis.wake_word.wake_word_installed", lambda: True)
    monkeypatch.setattr("jarvis.wake_word.download_wake_models", lambda models_dir: downloads.append(models_dir))

    cli.main(["preparar-voz"])

    assert downloads == [isolated_config_dir / "voz" / "activacion"]
    assert "Modelos guardados" in capsys.readouterr().out
