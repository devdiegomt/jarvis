"""Respuestas con voz: texto a nota de voz.

Dos motores detrás de la interfaz `Speaker`: Piper, en el equipo (el texto nunca sale del PC y
el audio se genera en memoria; opcional, grupo `voz`), y Azure AI Speech (`azure_speech.py`), con
Piper como respaldo. Cambiar de motor no toca el chat.
"""

import importlib.util
import io
import logging
import re
import threading
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from jarvis.config import SpeechSettings

# Lo que se lee en voz alta; el texto completo siempre llega también por escrito.
MAX_SPOKEN_CHARS = 1000
SPOKEN_REST_TEXT = "El resto te lo dejo por escrito."
OPUS_SAMPLE_RATE = 48_000  # frecuencia de las notas de voz de Telegram
INSTALL_HINT = "`uv sync` (instala el grupo de voz) y reinicia JARVIS"
PREPARE_HINT = "`uv run jarvis preparar-voz` en el PC"

logger = logging.getLogger("jarvis.chat")


class SpeechError(Exception):
    """No se pudo generar la voz. El mensaje está pensado para el usuario."""


class SpeechUnavailableError(SpeechError):
    """Falta instalar la voz o descargarla."""


class SpeechDownloadError(Exception):
    """No se pudo descargar la voz. El mensaje está pensado para el usuario."""


class Speaker(Protocol):
    name: str

    def speak(self, text: str) -> bytes:
        """Nota de voz (OGG/Opus) que dice `text`."""
        ...


# Carga una voz de Piper desde su archivo .onnx (reemplazable en los tests).
VoiceLoader = Callable[[Path], Any]


class PiperSpeaker:
    """Piper en el equipo. La voz se carga con la primera respuesta hablada y queda en memoria."""

    def __init__(
        self,
        voice: str,
        voices_dir: Path,
        load_voice: VoiceLoader | None = None,
        installed: Callable[[], bool] | None = None,
    ) -> None:
        self.name = f"Piper local (voz {voice})"
        self._voice_name = voice
        self._voices_dir = voices_dir
        self._load_voice = load_voice or _load_piper
        self._installed = installed or piper_installed
        self._voice: Any = None
        # Telegram y el micrófono del PC pueden pedir voz a la vez desde hilos distintos.
        self._lock = threading.Lock()

    def speak(self, text: str) -> bytes:
        pcm, sample_rate = self.synthesize(text)
        try:
            return encode_ogg_opus(pcm, sample_rate)
        except Exception as exc:  # fallo del codificador: no debe tumbar el chat
            logger.error("Falló la codificación de voz (%s).", type(exc).__name__)
            raise SpeechError("No pude generar la respuesta con voz.") from exc

    def synthesize(self, text: str) -> tuple[bytes, int]:
        """Audio PCM (16 bits, mono) y su frecuencia, para reproducirlo en los parlantes del PC."""
        with self._lock:
            voice = self._get_voice()
            try:
                chunks = list(voice.synthesize(spoken_text(text)))
            except Exception as exc:  # fallo interno de la voz: no debe tumbar el chat
                logger.error("Falló la síntesis de voz (%s).", type(exc).__name__)
                raise SpeechError("No pude generar la respuesta con voz.") from exc
        pcm = b"".join(chunk.audio_int16_bytes for chunk in chunks)
        if not pcm:
            raise SpeechError("No hay nada que decir en voz alta.")
        return pcm, chunks[0].sample_rate

    def preload(self) -> None:
        """Carga la voz ya (al arrancar), si está instalada y descargada."""
        with self._lock:
            try:
                started = time.monotonic()
                self._get_voice()
                logger.info("Piper listo en %.1f s.", time.monotonic() - started)
            except SpeechError as exc:
                logger.info("Piper no se precargó: %s", exc)

    def _get_voice(self) -> Any:
        if self._voice is not None:
            return self._voice
        if not self._installed():
            raise SpeechUnavailableError(
                f"La respuesta con voz no está instalada en el PC. Ejecuta {INSTALL_HINT}."
            )
        model = voice_file(self._voices_dir, self._voice_name)
        if not voice_downloaded(self._voices_dir, self._voice_name):
            raise SpeechUnavailableError(
                f"Falta descargar la voz «{self._voice_name}». Ejecuta {PREPARE_HINT}."
            )
        try:
            self._voice = self._load_voice(model)
        except Exception as exc:  # archivos dañados o incompletos
            logger.error("No se pudo cargar la voz (%s).", type(exc).__name__)
            raise SpeechUnavailableError(
                f"No pude cargar la voz «{self._voice_name}». Borra sus archivos de {self._voices_dir} "
                f"y ejecuta de nuevo {PREPARE_HINT}."
            ) from exc
        logger.info("Voz «%s» cargada.", self._voice_name)
        return self._voice


def spoken_text(text: str, limit: int = MAX_SPOKEN_CHARS) -> str:
    """Prepara una respuesta para leerla: sin enlaces ni emojis, y como mucho `limit` caracteres."""
    text = re.sub(r"https?://\S+", "(enlace)", text)
    text = "".join(char for char in text if unicodedata.category(char) not in ("So", "Cs"))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ([.,;:!?])", r"\1", text).strip()  # el espacio que deja un emoji quitado
    if len(text) <= limit:
        return text
    cut = max(text.rfind(sep, 0, limit) for sep in (". ", "\n", "? ", "! "))
    head = text[: cut + 1] if cut > 0 else text[:limit]
    return f"{head.strip()} {SPOKEN_REST_TEXT}"


def encode_ogg_opus(pcm: bytes, sample_rate: int) -> bytes:
    """Convierte audio PCM (16 bits, mono) en una nota de voz OGG/Opus, en memoria."""
    import av
    import numpy as np

    samples = np.frombuffer(pcm, dtype=np.int16).reshape(1, -1)
    frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
    frame.sample_rate = sample_rate
    resampler = av.AudioResampler(format="s16", layout="mono", rate=OPUS_SAMPLE_RATE)
    output = io.BytesIO()
    with av.open(output, mode="w", format="ogg") as container:
        stream = container.add_stream("libopus", rate=OPUS_SAMPLE_RATE, layout="mono")
        for resampled in [*resampler.resample(frame), *resampler.resample(None)]:
            container.mux(stream.encode(resampled))
        container.mux(stream.encode(None))
    return output.getvalue()


def build_speaker(settings: SpeechSettings) -> Speaker | None:
    """La voz configurada, o None si las respuestas con voz están desactivadas."""
    if not settings.enabled:
        return None
    piper = PiperSpeaker(settings.voice, settings.voices_dir)
    if settings.engine == "azure":
        from jarvis.azure_speech import AzureSpeaker

        return AzureSpeaker(settings.azure_key, settings.azure_region, settings.azure_voice, fallback=piper)
    return piper


def describe_speech(settings: SpeechSettings, installed: Callable[[], bool] | None = None) -> str:
    """Estado de las respuestas con voz, para `estado` y el arranque del bot (sin cargar la voz)."""
    if not settings.enabled:
        return "desactivadas (JARVIS_RESPUESTA_VOZ=no)"
    if settings.engine == "azure":
        ready = (installed or piper_installed)() and voice_downloaded(settings.voices_dir, settings.voice)
        backup = f"respaldo: Piper «{settings.voice}»" if ready else "sin respaldo en el PC"
        return f"activadas (Azure, voz {settings.azure_voice}; {backup})"
    if not (installed or piper_installed)():
        return f"⚠ no instaladas: ejecuta {INSTALL_HINT}"
    if not voice_downloaded(settings.voices_dir, settings.voice):
        return f"⚠ falta descargar la voz «{settings.voice}»: ejecuta {PREPARE_HINT}"
    return f"activadas (Piper local, voz {settings.voice})"


def piper_installed() -> bool:
    return importlib.util.find_spec("piper") is not None


def voice_file(voices_dir: Path, voice: str) -> Path:
    return voices_dir / f"{voice}.onnx"


def voice_downloaded(voices_dir: Path, voice: str) -> bool:
    model = voice_file(voices_dir, voice)
    config = model.with_name(f"{model.name}.json")
    return all(path.is_file() and path.stat().st_size > 0 for path in (model, config))


def download_voice(voice: str, voices_dir: Path) -> Path:
    """Descarga una voz de Piper (de Hugging Face) a `voices_dir`.

    Como la del modelo de Whisper, la descarga verifica HTTPS con el almacén del sistema.
    """
    import truststore
    from piper.download_voices import download_voice as piper_download

    voices_dir.mkdir(parents=True, exist_ok=True)
    truststore.inject_into_ssl()
    try:
        piper_download(voice, voices_dir)
    except Exception as exc:  # voz inexistente (404), red, certificados, disco lleno…
        model = voice_file(voices_dir, voice)
        for partial in (model, model.with_name(f"{model.name}.json")):
            partial.unlink(missing_ok=True)  # para que el siguiente intento descargue de nuevo
        raise SpeechDownloadError(
            f"No pude descargar la voz «{voice}» ({type(exc).__name__}). Revisa que el nombre "
            "exista (JARVIS_PIPER_VOZ) y tu conexión; si el error menciona certificados, revisa la "
            "sección de antivirus del README."
        ) from exc
    finally:
        truststore.extract_from_ssl()
    return voice_file(voices_dir, voice)


def _load_piper(model: Path) -> Any:
    from piper import PiperVoice

    return PiperVoice.load(model)
