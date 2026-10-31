"""Respuestas con voz con Azure AI Speech (voces neuronales de Microsoft), vía su API REST.

Se usa la API REST con `urllib` (y `truststore`, como en Telegram) en lugar del SDK de Microsoft,
que es pesado. Azure entrega el audio ya en el formato de las notas de voz de Telegram
(OGG/Opus) o en PCM para los parlantes del PC.

El texto de la respuesta se envía a Microsoft para convertirlo en voz. Si Azure falla, se usa la
voz de respaldo (Piper, en el PC) cuando está disponible.
"""

import logging
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from functools import cache
from typing import TypeVar
from xml.sax.saxutils import escape

import truststore

from jarvis.speech import Speaker, SpeechError, SpeechUnavailableError, spoken_text

TIMEOUT_SECONDS = 15
OGG_FORMAT = "ogg-48khz-16bit-mono-opus"
PCM_FORMAT = "raw-24khz-16bit-mono-pcm"
PCM_SAMPLE_RATE = 24_000

logger = logging.getLogger("jarvis.chat")

T = TypeVar("T")

# Envía la petición: (URL, cabeceras, cuerpo, tiempo máximo) → audio (reemplazable en los tests).
Caller = Callable[[str, dict[str, str], bytes, float], bytes]


class AzureAuthError(SpeechUnavailableError):
    """Clave o región rechazadas: reintentar no sirve."""


class AzureQuotaError(SpeechUnavailableError):
    """Se agotó el límite de uso (por ejemplo, el del plan gratuito)."""


class AzureSpeaker:
    """Voz de Azure; si falla, `fallback` (Piper) responde en su lugar."""

    def __init__(
        self,
        key: str,
        region: str,
        voice: str,
        fallback: Speaker | None = None,
        call: Caller | None = None,
    ) -> None:
        self.name = f"Azure (voz {voice})"
        self._key = key
        self._url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        self._voice = voice
        self._fallback = fallback
        self._call = call or http_post

    def speak(self, text: str) -> bytes:
        """Nota de voz OGG/Opus, lista para Telegram."""
        try:
            return self._synthesize(text, OGG_FORMAT)
        except SpeechError as exc:
            if self._fallback is None:
                raise
            return self._use_fallback(exc, lambda: self._fallback.speak(text))  # type: ignore[union-attr]

    def synthesize(self, text: str) -> tuple[bytes, int]:
        """Audio PCM (16 bits, mono) para los parlantes del PC."""
        try:
            return self._synthesize(text, PCM_FORMAT), PCM_SAMPLE_RATE
        except SpeechError as exc:
            synthesize = getattr(self._fallback, "synthesize", None)
            if synthesize is None:
                raise
            return self._use_fallback(exc, lambda: synthesize(text))

    def preload(self) -> None:
        """Azure no necesita carga; se precarga la voz de respaldo."""
        preload = getattr(self._fallback, "preload", None)
        if preload is not None:
            preload()

    def _synthesize(self, text: str, output_format: str) -> bytes:
        spoken = spoken_text(text)
        if not spoken:
            raise SpeechError("No hay nada que decir en voz alta.")
        headers = {
            "Ocp-Apim-Subscription-Key": self._key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": output_format,
            "User-Agent": "jarvis",
        }
        started = time.monotonic()
        audio = self._call(self._url, headers, self._ssml(spoken).encode("utf-8"), TIMEOUT_SECONDS)
        logger.info("Voz de Azure en %.1f s.", time.monotonic() - started)
        return audio

    def _ssml(self, text: str) -> str:
        language = "-".join(self._voice.split("-")[:2])  # es-CO-SalomeNeural → es-CO
        return (
            f"<speak version='1.0' xml:lang='{language}'>"
            f"<voice name='{self._voice}'>{escape(text)}</voice></speak>"
        )

    def _use_fallback(self, error: SpeechError, run: Callable[[], T]) -> T:
        """Responde con la voz de respaldo. Si tampoco puede, gana el error de Azure (es la causa)."""
        logger.warning("Azure no respondió (%s); uso la voz de respaldo.", error)
        try:
            return run()
        except SpeechError:
            raise error from None


def http_post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    """POST a Azure. Los errores nunca incluyen la clave (va en una cabecera, no en la URL)."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise _http_error(exc.code) from None
    except (urllib.error.URLError, OSError) as exc:  # sin red, DNS, certificados, tiempo agotado
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, ssl.SSLCertVerificationError):
            raise SpeechError(
                "No pude conectar con Azure: su certificado HTTPS no es de confianza en este equipo "
                "(suele ser un antivirus que inspecciona las conexiones; ver README)."
            ) from None
        raise SpeechError(f"No pude conectar con Azure ({type(reason).__name__}).") from None


def _http_error(code: int) -> SpeechError:
    if code in (401, 403):
        return AzureAuthError(
            "Azure rechazó la clave o la región de la voz: revisa AZURE_SPEECH_KEY y AZURE_SPEECH_REGION "
            "en el .env del PC."
        )
    if code == 429:
        return AzureQuotaError(
            "Se alcanzó el límite de uso de la voz de Azure (en el plan gratuito, hasta el próximo mes)."
        )
    if code == 400:
        return SpeechError("Azure rechazó la petición de voz (revisa que exista la voz en JARVIS_AZURE_VOZ).")
    return SpeechError(f"Azure no está disponible en este momento ({code}).")


@cache
def _ssl_context() -> ssl.SSLContext:
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
