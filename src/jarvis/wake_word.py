""""Hey JARVIS": detección de la palabra de activación en el PC.

Hoy con openWakeWord y su modelo "hey_jarvis", en el equipo (motor ONNX). El audio del micrófono
se analiza en memoria, en bloques de 80 ms, y se descarta. La interfaz `WakeWordDetector` permite
cambiar de motor más adelante (por ejemplo, un modelo propio para "Oye JARVIS").
"""

import importlib.util
import logging
import ssl
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import truststore

from jarvis.config import Settings
from jarvis.speech import voice_downloaded
from jarvis.voice import model_downloaded

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 1280  # 80 ms, el tamaño de bloque que espera openWakeWord
WAKE_MODEL = "hey_jarvis_v0.1.onnx"
FEATURE_MODELS = ("melspectrogram.onnx", "embedding_model.onnx")
MODELS_URL = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"
DOWNLOAD_TIMEOUT_SECONDS = 60
INSTALL_HINT = "`uv sync` (instala el grupo de voz) y reinicia JARVIS"
PREPARE_HINT = "`uv run python -m jarvis preparar-voz`"

logger = logging.getLogger("jarvis.chat")


class WakeWordUnavailableError(Exception):
    """Falta instalar la detección o descargar sus modelos. El mensaje está pensado para el usuario."""


class WakeWordDownloadError(Exception):
    """No se pudieron descargar los modelos. El mensaje está pensado para el usuario."""


class WakeWordDetector(Protocol):
    def process(self, frame: Any) -> bool:
        """Analiza 80 ms de audio (int16, 16 kHz, mono). True si se acaba de decir la palabra."""
        ...

    def reset(self) -> None:
        """Olvida el audio anterior (por ejemplo, tras una activación o mientras JARVIS habla)."""
        ...


# Carga el modelo de openWakeWord desde su carpeta (reemplazable en los tests).
ModelLoader = Callable[[Path], Any]


class OpenWakeWordDetector:
    def __init__(self, models_dir: Path, threshold: float, load_model: ModelLoader | None = None) -> None:
        if not wake_models_downloaded(models_dir):
            raise WakeWordUnavailableError(
                f"Faltan los modelos de la palabra de activación. Ejecuta {PREPARE_HINT}."
            )
        self._threshold = threshold
        self._model = (load_model or _load_openwakeword)(models_dir)

    def process(self, frame: Any) -> bool:
        scores = self._model.predict(frame)
        return max(scores.values(), default=0.0) >= self._threshold

    def reset(self) -> None:
        self._model.reset()


def wake_word_installed() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in ("openwakeword", "sounddevice"))


def wake_models_downloaded(models_dir: Path) -> bool:
    return all((models_dir / name).is_file() for name in (WAKE_MODEL, *FEATURE_MODELS))


def wake_word_problem(settings: Settings, installed: Callable[[], bool] | None = None) -> str | None:
    """Qué falta para usar "Hey JARVIS" (aunque esté desactivado en segundo plano), o None."""
    if not settings.speech.enabled:
        return "necesita las respuestas con voz (JARVIS_RESPUESTA_VOZ=local)"
    if not settings.voice.enabled:
        return "necesita la transcripción (JARVIS_TRANSCRIPCION=local)"
    if not (installed or wake_word_installed)():
        return f"no está instalada: ejecuta {INSTALL_HINT}"
    whisper_ready = model_downloaded(settings.voice.models_dir / settings.voice.model)
    # Con Azure, la voz no depende de Piper (es solo el respaldo).
    piper_ready = settings.speech.engine == "azure" or voice_downloaded(
        settings.speech.voices_dir, settings.speech.voice
    )
    if not (wake_models_downloaded(settings.wake_word.models_dir) and whisper_ready and piper_ready):
        return f"faltan modelos de voz: ejecuta {PREPARE_HINT}"
    return None


def describe_wake_word(settings: Settings, installed: Callable[[], bool] | None = None) -> str:
    """Estado de "Hey JARVIS", para `estado` y el arranque del bot (sin abrir el micrófono)."""
    if not settings.wake_word.enabled:
        return "desactivada (JARVIS_PALABRA_ACTIVACION=no)"
    problem = wake_word_problem(settings, installed)
    if problem is not None:
        return f"⚠ {problem}"
    return f"activa («Hey JARVIS», umbral {settings.wake_word.threshold:g})"


def download_wake_models(models_dir: Path, fetch: Callable[[str], bytes] | None = None) -> Path:
    """Descarga los modelos de openWakeWord (de GitHub) a `models_dir`, verificando HTTPS con el
    almacén de certificados del sistema. Cada archivo se escribe completo o no se escribe."""
    fetch = fetch or _https_get
    models_dir.mkdir(parents=True, exist_ok=True)
    for name in (WAKE_MODEL, *FEATURE_MODELS):
        target = models_dir / name
        if target.is_file():
            continue
        try:
            data = fetch(f"{MODELS_URL}/{name}")
        except OSError as exc:  # red, certificados (ssl.SSLError es un OSError), HTTP
            raise WakeWordDownloadError(
                f"No pude descargar {name} ({type(exc).__name__}). Revisa tu conexión; si el error "
                "menciona certificados, revisa la sección de antivirus del README."
            ) from exc
        partial = target.with_suffix(".part")
        partial.write_bytes(data)
        partial.replace(target)
    return models_dir


def _https_get(url: str) -> bytes:
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS, context=context) as response:
        return response.read()


def _load_openwakeword(models_dir: Path) -> Any:
    from openwakeword.model import Model

    return Model(
        wakeword_models=[str(models_dir / WAKE_MODEL)],
        inference_framework="onnx",
        melspec_model_path=str(models_dir / FEATURE_MODELS[0]),
        embedding_model_path=str(models_dir / FEATURE_MODELS[1]),
    )
