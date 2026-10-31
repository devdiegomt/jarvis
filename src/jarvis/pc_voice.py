""""Hey JARVIS" en el PC: palabra de activación, tu pedido y la respuesta en voz alta.

Flujo: el micrófono se analiza en bloques de 80 ms solo para detectar la palabra de activación
(nada se guarda). Al detectarla suena un tono, se graba el pedido hasta que te callas, se
transcribe con Whisper y pasa al mismo `ChatService` que usa Telegram, con un canal propio
(`PcVoiceChannel`) que habla por los parlantes en vez de enviar mensajes. Mientras JARVIS habla,
el micrófono se ignora para que no se escuche a sí mismo.
"""

import io
import logging
import queue
import threading
import time
import uuid
import wave
from collections.abc import Callable, Iterator
from typing import Any, Protocol

import numpy as np

from jarvis.assistant import Assistant
from jarvis.chat import ButtonAnswer, ChannelError, ChatEvent, ChatService, IncomingMessage, VoiceNote
from jarvis.prompts import build_pc_voice_system_prompt
from jarvis.speech import SpeechError
from jarvis.voice import TranscriptionError, Transcriber
from jarvis.wake_word import (
    FRAME_SAMPLES,
    SAMPLE_RATE,
    OpenWakeWordDetector,
    WakeWordDetector,
    WakeWordUnavailableError,
    wake_word_problem,
)

CHANNEL_NAME = "pc"
SENDER = "local"
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE
MAX_REQUEST_SECONDS = 15
NO_SPEECH_SECONDS = 4  # si no empiezas a hablar en este tiempo tras el tono, se cancela
END_SILENCE_SECONDS = 0.7  # silencio que marca el final del pedido (más largo = más espera)
MIN_SPEECH_RMS = 300.0  # volumen mínimo (int16) para considerar que hay voz
NOISE_FACTOR = 3.0  # la voz debe superar el ruido de fondo medido por este factor
SPEAKING_TAIL_SECONDS = 0.3  # tras hablar, el micrófono sigue ignorado un instante (eco)
CONFIRM_SUFFIX = "¿Sí o no?"
NOT_HEARD_TEXT = "No te escuché. Dime «Hey JARVIS» de nuevo cuando quieras."
NOT_HEARD_ANSWER_TEXT = "No te escuché. ¿Sí o no?"

logger = logging.getLogger("jarvis.chat")


class AudioDeviceError(Exception):
    """No se pudo usar el micrófono o los parlantes. El mensaje está pensado para el usuario."""


class AudioDevice(Protocol):
    def frames(self) -> Iterator[np.ndarray]:
        """Bloques de 80 ms del micrófono (int16, 16 kHz, mono), sin fin."""
        ...

    def flush(self) -> None:
        """Descarta el audio del micrófono que aún no se leyó."""
        ...

    def play(self, samples: np.ndarray, sample_rate: int) -> None:
        """Reproduce audio (int16, mono) y espera a que termine."""
        ...


class PcmSpeaker(Protocol):
    def synthesize(self, text: str) -> tuple[bytes, int]: ...


class PcVoiceChannel:
    """Implementa `ChatChannel` hablando por los parlantes del PC."""

    name = CHANNEL_NAME

    def __init__(
        self,
        speaker: PcmSpeaker,
        audio: AudioDevice,
        on_say: Callable[[str], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._speaker = speaker
        self._audio = audio
        self._on_say = on_say
        self._sleep = sleep
        self.speaking = threading.Event()
        self.expecting_answer = threading.Event()

    def send_text(self, to: str, text: str) -> None:
        self.say(text)

    def show_typing(self, to: str) -> None:
        pass  # el tono de activación ya indica que JARVIS te escuchó

    def send_with_buttons(self, to: str, text: str, buttons: list[tuple[str, str]]) -> None:
        """Solo se usa para confirmar acciones: se pregunta en voz alta y se escucha la respuesta."""
        self.say(f"{text} {CONFIRM_SUFFIX}")
        self.expecting_answer.set()

    def replace_message(self, to: str, handle: Any, text: str) -> None:
        pass

    def acknowledge(self, answer: ButtonAnswer, text: str = "") -> None:
        pass

    def download_voice(self, note: VoiceNote) -> bytes:
        raise ChannelError("En el PC el audio se transcribe al grabarlo.")

    def send_voice(self, to: str, audio: bytes) -> None:
        pass  # en el PC, `send_text` ya habla

    def say(self, text: str) -> None:
        if self._on_say is not None:
            self._on_say(text)
        try:
            started = time.monotonic()
            pcm, sample_rate = self._speaker.synthesize(text)
            logger.info("Voz generada en %.1f s.", time.monotonic() - started)
        except SpeechError as exc:
            raise ChannelError(str(exc)) from exc
        self.play(np.frombuffer(pcm, dtype=np.int16), sample_rate)

    def chime(self, rising: bool = True) -> None:
        self.play(chime_samples(rising), SAMPLE_RATE)

    def play(self, samples: np.ndarray, sample_rate: int) -> None:
        self.speaking.set()
        try:
            self._audio.play(samples, sample_rate)
        except AudioDeviceError as exc:
            raise ChannelError(str(exc)) from exc
        finally:
            self._sleep(SPEAKING_TAIL_SECONDS)
            self.speaking.clear()


class WakeWordListener:
    """Escucha el micrófono, detecta "Hey JARVIS" y entrega el pedido transcrito al chat."""

    def __init__(
        self,
        audio: AudioDevice,
        detector: WakeWordDetector,
        channel: PcVoiceChannel,
        transcriber: Transcriber,
        submit: Callable[[ChatEvent], None],
        on_event: Callable[[str], None] = lambda _text: None,
    ) -> None:
        self._audio = audio
        self._detector = detector
        self._channel = channel
        self._transcriber = transcriber
        self._submit = submit
        self._on_event = on_event  # en la consola muestra lo que pasa; en segundo plano no se usa
        self._noise = NoiseFloor()

    def run_forever(self) -> None:
        frames = iter(self._audio.frames())
        was_speaking = False
        for frame in frames:
            if self._channel.speaking.is_set():
                was_speaking = True
                continue  # JARVIS está hablando: no escucharse a sí mismo
            if was_speaking:
                was_speaking = False
                self._audio.flush()
                self._detector.reset()
            if self._channel.expecting_answer.is_set():
                self._channel.expecting_answer.clear()
                self._handle_answer(frames, frame)
                continue
            if self._detector.process(frame):
                self._handle_activation(frames)
            else:
                self._noise.update(frame)

    def _handle_activation(self, frames: Iterator[np.ndarray]) -> None:
        logger.info("Palabra de activación detectada.")
        self._on_event("🔔 Te escucho…")
        self._detector.reset()
        self._say_safely(chime=True)
        audio = record_request(frames, self._noise.threshold())
        if audio is None:
            self._on_event("(no escuché nada)")
            self._say_safely(NOT_HEARD_TEXT)
            return
        self._transcribe_and_submit(audio)

    def _handle_answer(self, frames: Iterator[np.ndarray], first: np.ndarray) -> None:
        """Respuesta a una confirmación: se graba sin palabra de activación (dos intentos)."""
        audio = record_request(frames, self._noise.threshold(), first=first)
        if audio is None:
            self._say_safely(NOT_HEARD_ANSWER_TEXT)
            audio = record_request(frames, self._noise.threshold())
        if audio is None:
            self._submit_text("no", transcribed=False)  # sin respuesta: se cancela, como en Telegram
            return
        self._transcribe_and_submit(audio)

    def _transcribe_and_submit(self, audio: np.ndarray) -> None:
        started = time.monotonic()
        try:
            text = self._transcriber.transcribe(to_wav(audio))
        except TranscriptionError as exc:
            self._say_safely(str(exc))
            return
        # Solo duraciones: lo que se dijo nunca va al registro.
        logger.info(
            "Pedido de %.1f s transcrito en %.1f s.", len(audio) / SAMPLE_RATE, time.monotonic() - started
        )
        if not text:
            self._say_safely(NOT_HEARD_TEXT)
            return
        self._on_event(f"🎙 Entendí: «{text}»")
        self._submit_text(text, transcribed=True)

    def _submit_text(self, text: str, transcribed: bool) -> None:
        message_id = f"pc:{uuid.uuid4().hex[:12]}"
        self._submit(IncomingMessage(id=message_id, sender=SENDER, text=text, transcribed=transcribed))

    def _say_safely(self, text: str = "", chime: bool = False) -> None:
        try:
            if chime:
                self._channel.chime()
            else:
                self._channel.say(text)
        except ChannelError as exc:
            logger.warning("No se pudo hablar por los parlantes: %s", exc)
        # Tras el tono se conserva lo captado, para que puedas decir "Hey JARVIS, ¿qué tengo hoy?"
        # de corrido; tras una frase de JARVIS, en cambio, lo captado es su propia voz.
        if not chime:
            self._audio.flush()


class NoiseFloor:
    """Volumen del ruido de fondo, medido mientras nadie le habla a JARVIS."""

    def __init__(self, initial: float = 100.0) -> None:
        self._level = initial

    def update(self, frame: np.ndarray) -> None:
        self._level = 0.95 * self._level + 0.05 * rms(frame)

    def threshold(self) -> float:
        return max(MIN_SPEECH_RMS, self._level * NOISE_FACTOR)


def record_request(
    frames: Iterator[np.ndarray], threshold: float, first: np.ndarray | None = None
) -> np.ndarray | None:
    """Graba hasta que la voz termina (1 s de silencio) o pasan 15 s. None si nadie habló."""
    max_frames = round(MAX_REQUEST_SECONDS / FRAME_SECONDS)
    no_speech_frames = round(NO_SPEECH_SECONDS / FRAME_SECONDS)
    end_silence_frames = round(END_SILENCE_SECONDS / FRAME_SECONDS)
    chunks: list[np.ndarray] = []
    started, silent = False, 0
    source = iter(frames) if first is None else _prepend(first, frames)
    for frame in source:
        chunks.append(frame)
        if rms(frame) >= threshold:
            started, silent = True, 0
        elif started:
            silent += 1
        if started and silent >= end_silence_frames:
            break
        if not started and len(chunks) >= no_speech_frames:
            return None
        if len(chunks) >= max_frames:
            break
    return np.concatenate(chunks) if started else None


def rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(frame.astype(np.float64))))) if frame.size else 0.0


def to_wav(samples: np.ndarray) -> bytes:
    """WAV en memoria (16 kHz, mono) para Whisper; nunca se escribe en disco."""
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(samples.astype(np.int16).tobytes())
    return output.getvalue()


def chime_samples(rising: bool = True) -> np.ndarray:
    """Dos notas cortas: subiendo al activarse."""
    notes = (660.0, 880.0) if rising else (880.0, 660.0)
    t = np.arange(int(SAMPLE_RATE * 0.09)) / SAMPLE_RATE
    fade = np.minimum(1.0, np.minimum(t, t[::-1]) * 200)  # sin chasquidos al empezar y terminar
    tone = np.concatenate([np.sin(2 * np.pi * f * t) * fade for f in notes])
    return (tone * 6000).astype(np.int16)


def _prepend(first: np.ndarray, frames: Iterator[np.ndarray]) -> Iterator[np.ndarray]:
    yield first
    yield from frames


class SoundDeviceAudio:
    """Micrófono y parlantes predeterminados de Windows, con `sounddevice` (PortAudio)."""

    QUEUE_SECONDS = 10  # si JARVIS se atrasa (por ejemplo, transcribiendo), se descarta lo más viejo

    def __init__(self) -> None:
        try:
            import sounddevice
        except (ImportError, OSError) as exc:  # no instalado, o falta la biblioteca de audio
            raise AudioDeviceError(f"No pude usar el audio del PC ({type(exc).__name__}).") from exc
        self._sd = sounddevice
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=round(self.QUEUE_SECONDS / FRAME_SECONDS))

    def frames(self) -> Iterator[np.ndarray]:
        def on_audio(indata: np.ndarray, _frames: int, _time: Any, _status: Any) -> None:
            if self._queue.full():
                self._drop_oldest()
            self._queue.put_nowait(indata[:, 0].copy())

        try:
            stream = self._sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME_SAMPLES, callback=on_audio
            )
        except Exception as exc:  # sin micrófono, o en uso por otra aplicación
            raise AudioDeviceError(f"No pude abrir el micrófono ({type(exc).__name__}).") from exc
        with stream:
            while True:
                yield self._queue.get()

    def flush(self) -> None:
        while not self._queue.empty():
            self._drop_oldest()

    def play(self, samples: np.ndarray, sample_rate: int) -> None:
        try:
            self._sd.play(samples, sample_rate)
            self._sd.wait()
        except Exception as exc:  # sin parlantes, o el dispositivo desapareció
            raise AudioDeviceError(f"No pude reproducir audio ({type(exc).__name__}).") from exc

    def _drop_oldest(self) -> None:
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass


# --- Arranque ----------------------------------------------------------------


def start_pc_voice(
    assistant: Assistant, console: bool, audio: AudioDevice | None = None, detector: WakeWordDetector | None = None
) -> threading.Thread | None:
    """Arranca "Hey JARVIS" en un hilo, con su propio chat. None si no se puede (queda en el registro)."""
    problem = wake_word_problem(assistant.settings)
    if problem is not None or assistant.speaker is None or assistant.transcriber is None:
        _report(f"Hey JARVIS no arrancó: {problem or 'falta la voz'}.", console)
        return None
    try:
        audio = audio or SoundDeviceAudio()
        wake = assistant.settings.wake_word
        detector = detector or OpenWakeWordDetector(wake.models_dir, wake.threshold)
    except (AudioDeviceError, WakeWordUnavailableError) as exc:
        _report(f"Hey JARVIS no arrancó: {exc}", console)
        return None
    except Exception as exc:  # modelos dañados, onnxruntime bloqueado…: el resto de JARVIS sigue
        _report(f"Hey JARVIS no arrancó: no pude cargar la detección ({type(exc).__name__}).", console)
        return None

    speaker: PcmSpeaker = assistant.speaker  # type: ignore[assignment]  # Piper sabe dar audio PCM
    channel = PcVoiceChannel(speaker, audio, on_say=_print_reply if console else None)
    now, memories = assistant.now, assistant.memories
    chat = ChatService(
        channel=channel,
        store=assistant.conversations,
        agent_factory=assistant.agent_factory,
        system_prompt=lambda: build_pc_voice_system_prompt(now().date(), memories.all()),
        now=now,
        memories=memories,
    )
    chat.start()
    on_event: Callable[[str], None] = print if console else lambda _text: None
    listener = WakeWordListener(audio, detector, channel, assistant.transcriber, chat.submit, on_event=on_event)

    def listen() -> None:
        try:
            listener.run_forever()
        except AudioDeviceError as exc:
            _report(f"Hey JARVIS se detuvo: {exc}", console)

    thread = threading.Thread(target=listen, name="jarvis-hey-jarvis", daemon=True)
    thread.start()
    logger.info("Hey JARVIS escuchando en el PC.")
    return thread


def _report(message: str, console: bool) -> None:
    logger.warning(message)
    if console:
        print(message)


def _print_reply(text: str) -> None:
    print(f"JARVIS: {text}\n")
