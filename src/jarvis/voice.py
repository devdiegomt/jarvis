"""Notas de voz: transcripción de audio a texto.

Hoy la transcripción es local, con Whisper (`faster-whisper`): el audio nunca sale del equipo,
se procesa en memoria y no se guarda en disco. La interfaz `Transcriber` permite cambiar de
motor más adelante (por ejemplo, uno en la nube) sin tocar el chat.

`faster-whisper` es una dependencia opcional (grupo `voz`): sin ella, JARVIS funciona igual y
solo responde que las notas de voz no están instaladas.
"""

import importlib.util
import io
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from jarvis.config import VoiceSettings

MAX_VOICE_SECONDS = 5 * 60
LANGUAGE = "es"
# Archivos que deja `preparar-voz`; si están, el modelo se puede cargar sin internet.
MODEL_FILES = ("model.bin", "config.json")
INSTALL_HINT = "`uv sync` (instala el grupo de voz) y reinicia JARVIS"
PREPARE_HINT = "`uv run jarvis preparar-voz` en el PC"

logger = logging.getLogger("jarvis.chat")


class TranscriptionError(Exception):
    """No se pudo transcribir. El mensaje está pensado para el usuario."""


class VoiceUnavailableError(TranscriptionError):
    """Falta instalar la transcripción o descargar el modelo."""


class VoiceDownloadError(Exception):
    """No se pudo descargar el modelo. El mensaje está pensado para el usuario."""


class Transcriber(Protocol):
    name: str

    def transcribe(self, audio: bytes) -> str:
        """Texto de un audio (por ejemplo, una nota de voz OGG/Opus). Vacío si no se oye nada."""
        ...


# Carga un modelo de Whisper desde su carpeta (reemplazable en los tests).
ModelLoader = Callable[[Path], Any]


class WhisperTranscriber:
    """Whisper en el equipo. El modelo se carga con la primera nota de voz y queda en memoria."""

    def __init__(
        self,
        model: str,
        models_dir: Path,
        load_model: ModelLoader | None = None,
        installed: Callable[[], bool] | None = None,
    ) -> None:
        self.name = f"Whisper local (modelo {model})"
        self._model_name = model
        self._model_dir = models_dir / model
        self._load_model = load_model or _load_whisper
        self._installed = installed or whisper_installed
        self._model: Any = None
        # Telegram y el micrófono del PC pueden transcribir a la vez desde hilos distintos.
        self._lock = threading.Lock()

    def transcribe(self, audio: bytes) -> str:
        with self._lock:
            model = self._get_model()
            try:
                # `vad_filter` descarta los silencios, que es donde Whisper suele inventar frases.
                # `beam_size=1` (búsqueda simple) es mucho más rápido en CPU y basta para frases cortas.
                segments, _info = model.transcribe(
                    io.BytesIO(audio),
                    language=LANGUAGE,
                    vad_filter=True,
                    beam_size=1,
                    condition_on_previous_text=False,
                )
                return " ".join(segment.text.strip() for segment in segments).strip()
            except Exception as exc:  # audio dañado o fallo interno del modelo: no debe tumbar el chat
                logger.error("Falló la transcripción (%s).", type(exc).__name__)
                raise TranscriptionError("No pude transcribir el audio. Inténtalo de nuevo.") from exc

    def preload(self) -> None:
        """Carga el modelo ya (al arrancar), si está instalado y descargado."""
        with self._lock:
            try:
                started = time.monotonic()
                self._get_model()
                logger.info("Whisper listo en %.1f s.", time.monotonic() - started)
            except TranscriptionError as exc:
                logger.info("Whisper no se precargó: %s", exc)

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        if not self._installed():
            raise VoiceUnavailableError(
                f"Las notas de voz no están instaladas en el PC. Ejecuta {INSTALL_HINT}."
            )
        if not model_downloaded(self._model_dir):
            raise VoiceUnavailableError(
                f"Falta descargar el modelo de voz «{self._model_name}». Ejecuta {PREPARE_HINT}."
            )
        try:
            self._model = self._load_model(self._model_dir)
        except Exception as exc:  # archivos dañados o incompletos
            logger.error("No se pudo cargar el modelo de voz (%s).", type(exc).__name__)
            raise VoiceUnavailableError(
                f"No pude cargar el modelo de voz «{self._model_name}». Bórralo de {self._model_dir} "
                f"y ejecuta de nuevo {PREPARE_HINT}."
            ) from exc
        logger.info("Modelo de voz «%s» cargado.", self._model_name)
        return self._model


def build_transcriber(settings: VoiceSettings) -> Transcriber | None:
    """El transcriptor configurado, o None si las notas de voz están desactivadas."""
    if not settings.enabled:
        return None
    return WhisperTranscriber(settings.model, settings.models_dir)


def describe_voice(settings: VoiceSettings, installed: Callable[[], bool] | None = None) -> str:
    """Estado de las notas de voz, para `estado` y el arranque del bot (sin cargar el modelo)."""
    if not settings.enabled:
        return "desactivadas (JARVIS_TRANSCRIPCION=no)"
    if not (installed or whisper_installed)():
        return f"⚠ no instaladas: ejecuta {INSTALL_HINT}"
    if not model_downloaded(settings.models_dir / settings.model):
        return f"⚠ falta descargar el modelo «{settings.model}»: ejecuta {PREPARE_HINT}"
    return f"activadas (Whisper local, modelo {settings.model})"


def whisper_installed() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def model_downloaded(model_dir: Path) -> bool:
    return all((model_dir / name).is_file() for name in MODEL_FILES)


def download_model(model: str, models_dir: Path) -> Path:
    """Descarga un modelo de Whisper (de Hugging Face) a `models_dir/<modelo>`.

    La descarga verifica HTTPS con el almacén de certificados del sistema, como el resto de
    JARVIS, para que funcione con antivirus o proxys que inspeccionan el tráfico.
    """
    import truststore
    from faster_whisper import available_models
    from faster_whisper import download_model as whisper_download

    if model not in available_models():
        raise VoiceDownloadError(
            f"«{model}» no es un modelo de Whisper conocido (JARVIS_WHISPER_MODELO). "
            f"Opciones: {', '.join(available_models())}."
        )
    target = models_dir / model
    truststore.inject_into_ssl()
    try:
        whisper_download(model, output_dir=str(target))
    except Exception as exc:  # red, certificados, disco lleno…
        raise VoiceDownloadError(
            f"No pude descargar el modelo ({type(exc).__name__}). Revisa tu conexión y vuelve a "
            "intentarlo; si el error menciona certificados, revisa la sección de antivirus del README."
        ) from exc
    finally:
        truststore.extract_from_ssl()
    return target


def _load_whisper(model_dir: Path) -> Any:
    from faster_whisper import WhisperModel

    # CPU con int8: funciona en cualquier PC sin tarjeta gráfica y usa menos memoria.
    return WhisperModel(str(model_dir), device="cpu", compute_type="int8")
