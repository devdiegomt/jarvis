import sys
import types
from pathlib import Path
from typing import Any

import pytest
import truststore

from jarvis import cli
from jarvis.config import ConfigError, VoiceSettings, load_settings, load_voice_settings
from jarvis.voice import (
    TranscriptionError,
    VoiceDownloadError,
    VoiceUnavailableError,
    WhisperTranscriber,
    build_transcriber,
    describe_voice,
    download_model,
    model_downloaded,
)

# --- Configuración ----------------------------------------------------------


def test_voice_defaults(isolated_config_dir: Path) -> None:
    voice = load_settings({"ANTHROPIC_API_KEY": "sk-test"}).voice

    assert voice.enabled and voice.engine == "local"
    assert voice.model == "small"
    assert voice.models_dir == isolated_config_dir / "voz"


def test_voice_can_be_disabled_and_model_changed() -> None:
    voice = load_voice_settings({"JARVIS_TRANSCRIPCION": "No", "JARVIS_WHISPER_MODELO": "Large-v3-Turbo"})

    assert not voice.enabled
    assert voice.model == "large-v3-turbo"


@pytest.mark.parametrize(
    ("name", "value"),
    [("JARVIS_TRANSCRIPCION", "nube"), ("JARVIS_WHISPER_MODELO", "../otro"), ("JARVIS_WHISPER_MODELO", "a b")],
)
def test_invalid_voice_settings_fail(name: str, value: str) -> None:
    with pytest.raises(ConfigError, match=name):
        load_voice_settings({name: value})


# --- Transcripción ----------------------------------------------------------


class Segment:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeModel:
    def __init__(self, texts: list[str] | None = None, error: Exception | None = None) -> None:
        self.texts = texts or []
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio: Any, **options: Any) -> tuple[Any, None]:
        self.calls.append({"audio": audio.read(), **options})

        def segments() -> Any:  # como en faster-whisper, el trabajo ocurre al recorrer los segmentos
            if self.error:
                raise self.error
            yield from (Segment(text) for text in self.texts)

        return segments(), None


def downloaded_model(models_dir: Path, name: str = "small") -> Path:
    model_dir = models_dir / name
    model_dir.mkdir(parents=True)
    (model_dir / "model.bin").write_bytes(b"")
    (model_dir / "config.json").write_text("{}")
    return model_dir


def transcriber(tmp_path: Path, model: FakeModel, installed: bool = True) -> tuple[WhisperTranscriber, list[Path]]:
    loads: list[Path] = []

    def load(path: Path) -> FakeModel:
        loads.append(path)
        return model

    return WhisperTranscriber("small", tmp_path, load_model=load, installed=lambda: installed), loads


def test_transcribes_in_spanish_and_loads_the_model_once(tmp_path: Path) -> None:
    model = FakeModel([" Recuérdame llamar a Laura ", "a las cinco."])
    model_dir = downloaded_model(tmp_path)
    whisper, loads = transcriber(tmp_path, model)

    assert whisper.transcribe(b"ogg") == "Recuérdame llamar a Laura a las cinco."
    whisper.transcribe(b"ogg")

    assert loads == [model_dir]
    assert model.calls[0] == {"audio": b"ogg", "language": "es", "vad_filter": True}


def test_not_installed_explains_how_to_install(tmp_path: Path) -> None:
    downloaded_model(tmp_path)
    whisper, _ = transcriber(tmp_path, FakeModel(), installed=False)

    with pytest.raises(VoiceUnavailableError, match="uv sync"):
        whisper.transcribe(b"ogg")


def test_missing_model_explains_how_to_download_it(tmp_path: Path) -> None:
    whisper, loads = transcriber(tmp_path, FakeModel())

    with pytest.raises(VoiceUnavailableError, match="preparar-voz"):
        whisper.transcribe(b"ogg")
    assert loads == []


def test_damaged_model_is_reported(tmp_path: Path) -> None:
    downloaded_model(tmp_path)

    def broken(_path: Path) -> Any:
        raise RuntimeError("archivo corrupto")

    whisper = WhisperTranscriber("small", tmp_path, load_model=broken, installed=lambda: True)

    with pytest.raises(VoiceUnavailableError, match="No pude cargar el modelo"):
        whisper.transcribe(b"ogg")


def test_unreadable_audio_is_a_transcription_error(tmp_path: Path) -> None:
    downloaded_model(tmp_path)
    whisper, _ = transcriber(tmp_path, FakeModel(error=ValueError("audio inválido")))

    with pytest.raises(TranscriptionError, match="No pude transcribir"):
        whisper.transcribe(b"no es audio")


def test_build_transcriber(tmp_path: Path) -> None:
    assert build_transcriber(VoiceSettings("no", "small", tmp_path)) is None
    assert isinstance(build_transcriber(VoiceSettings("local", "small", tmp_path)), WhisperTranscriber)


@pytest.mark.parametrize(
    ("engine", "installed", "downloaded", "expected"),
    [
        ("no", True, True, "desactivadas"),
        ("local", False, True, "no instaladas"),
        ("local", True, False, "falta descargar el modelo «small»"),
        ("local", True, True, "activadas (Whisper local, modelo small)"),
    ],
)
def test_describe_voice(tmp_path: Path, engine: str, installed: bool, downloaded: bool, expected: str) -> None:
    if downloaded:
        downloaded_model(tmp_path)

    assert expected in describe_voice(VoiceSettings(engine, "small", tmp_path), installed=lambda: installed)


# --- Descarga del modelo ----------------------------------------------------


@pytest.fixture
def fake_faster_whisper(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    """Sustituye `faster_whisper` (no está instalado en la CI) y registra las descargas."""
    record = types.SimpleNamespace(downloads=[], injected_during_download=None, error=None)

    def fake_download(name: str, output_dir: str) -> str:
        record.injected_during_download = sys.modules["ssl"].SSLContext is truststore.SSLContext
        if record.error:
            raise record.error
        record.downloads.append((name, output_dir))
        downloaded_model(Path(output_dir).parent, name)
        return output_dir

    module = types.ModuleType("faster_whisper")
    module.available_models = lambda: ["tiny", "small", "large-v3-turbo"]  # type: ignore[attr-defined]
    module.download_model = fake_download  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    return record


def test_download_uses_the_system_trust_store_only_while_downloading(
    tmp_path: Path, fake_faster_whisper: types.SimpleNamespace
) -> None:
    import ssl

    target = download_model("small", tmp_path)

    assert target == tmp_path / "small" and model_downloaded(target)
    assert fake_faster_whisper.downloads == [("small", str(tmp_path / "small"))]
    assert fake_faster_whisper.injected_during_download
    assert ssl.SSLContext is not truststore.SSLContext  # se restaura al terminar


def test_download_rejects_unknown_models(tmp_path: Path, fake_faster_whisper: types.SimpleNamespace) -> None:
    with pytest.raises(VoiceDownloadError, match="tiny, small, large-v3-turbo"):
        download_model("gigante", tmp_path)
    assert fake_faster_whisper.downloads == []


def test_download_errors_are_explained(tmp_path: Path, fake_faster_whisper: types.SimpleNamespace) -> None:
    import ssl

    fake_faster_whisper.error = ConnectionError("sin red")

    with pytest.raises(VoiceDownloadError, match="ConnectionError"):
        download_model("small", tmp_path)
    assert ssl.SSLContext is not truststore.SSLContext


# --- Comando preparar-voz ---------------------------------------------------


def prepare(monkeypatch: pytest.MonkeyPatch, env: dict[str, str], installed: bool = True) -> None:
    monkeypatch.setattr(cli, "read_env", lambda: env)
    monkeypatch.setattr("jarvis.voice.whisper_installed", lambda: installed)
    cli.main(["preparar-voz"])


def test_prepare_voice_downloads_the_model(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    isolated_config_dir: Path,
    fake_faster_whisper: types.SimpleNamespace,
) -> None:
    prepare(monkeypatch, {"JARVIS_WHISPER_MODELO": "tiny"})

    assert fake_faster_whisper.downloads == [("tiny", str(isolated_config_dir / "voz" / "tiny"))]
    assert "Listo: modelo guardado" in capsys.readouterr().out


def test_prepare_voice_skips_a_model_already_downloaded(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    isolated_config_dir: Path,
    fake_faster_whisper: types.SimpleNamespace,
) -> None:
    downloaded_model(isolated_config_dir / "voz")

    prepare(monkeypatch, {})

    assert fake_faster_whisper.downloads == []
    assert "ya está descargado" in capsys.readouterr().out


def test_prepare_voice_without_the_voice_group(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        prepare(monkeypatch, {}, installed=False)

    assert "uv sync" in capsys.readouterr().err


def test_prepare_voice_when_disabled(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prepare(monkeypatch, {"JARVIS_TRANSCRIPCION": "no"})

    assert "desactivadas" in capsys.readouterr().out
