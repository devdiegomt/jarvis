"""Chat con JARVIS por un canal de mensajería, independiente del canal concreto (hoy Telegram).

El servicio procesa los eventos de uno en uno y en orden en un único hilo. Eso permite que
una confirmación espere la respuesta leyendo la misma cola: el siguiente evento del usuario
(un botón o un "s/n" escrito) es la respuesta.
"""

import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

import anthropic

from jarvis.agent import Agent
from jarvis.confirmation import parse_yes_no
from jarvis.long_term_memory import MemoryStore
from jarvis.memory import Conversation, ConversationStore
from jarvis.speech import Speaker, SpeechError, SpeechUnavailableError
from jarvis.tools import Confirmer
from jarvis.voice import MAX_VOICE_SECONDS, TranscriptionError, Transcriber

CONFIRMATION_TIMEOUT_SECONDS = 5 * 60
PURGE_INTERVAL = timedelta(hours=24)

WELCOME_TEXT = (
    "Hola, soy JARVIS. Pregúntame por tu agenda o pídeme ayuda con tu día.\n\n"
    "Puedes escribirme o enviarme notas de voz.\n\n"
    "Comandos: /nuevo para empezar una conversación nueva, /ayuda para ver esta ayuda."
)
HELP_TEXT = (
    "Pregúntame, por ejemplo: «¿Qué tengo hoy?» o «Recuérdame a las 5 llamar a Laura». "
    "También entiendo notas de voz.\n\n"
    "/nuevo: empezar una conversación nueva\n/voz: elegir cuándo te respondo con voz\n"
    "/memoria: ver lo que recuerdo de ti\n/ayuda: ver esta ayuda"
)
NEW_CONVERSATION_TEXT = "Listo, empezamos una conversación nueva."
ONLY_TEXT_TEXT = "Por ahora entiendo mensajes de texto y notas de voz."
VOICE_DISABLED_TEXT = "Las notas de voz están desactivadas (JARVIS_TRANSCRIPCION=no). Escríbeme el mensaje."
VOICE_TOO_LONG_TEXT = f"La nota de voz es muy larga: envíame una de máximo {MAX_VOICE_SECONDS // 60} minutos."
VOICE_DOWNLOAD_ERROR_TEXT = "No pude descargar la nota de voz. Inténtalo de nuevo."
VOICE_EMPTY_TEXT = "No logré entender nada en la nota de voz. ¿Me lo repites o me lo escribes?"
HEARD_TEMPLATE = "🎙 Entendí: «{}»"
VOICE_MARK = "(nota de voz)"
NO_MEMORIES_TEXT = (
    "Aún no recuerdo nada de ti. Cuéntame cosas que quieras que tenga presentes "
    "(personas, preferencias, rutinas) y las iré anotando."
)
MEMORIES_FOOTER = "Para que olvide algo, dime por ejemplo «olvida el {id}»."
SPEECH_DISABLED_TEXT = "Las respuestas con voz están desactivadas (JARVIS_RESPUESTA_VOZ=no)."

# Cuándo responder con voz (comando /voz). "espejo": solo si el usuario envió una nota de voz.
VOICE_PREFERENCE = "respuesta_voz"
DEFAULT_VOICE_MODE = "espejo"
# Modo: (botón, cómo se describe ahora, confirmación al elegirlo).
VOICE_MODES = {
    "espejo": (
        "🎙 Si me hablas",
        "solo cuando me envías una nota de voz",
        "Listo: te responderé con voz cuando me hables.",
    ),
    "siempre": ("🔊 Siempre", "siempre", "Listo: te responderé siempre con voz."),
    "nunca": ("🔇 Nunca", "nunca", "Listo: te responderé solo por escrito."),
}
VOICE_BUTTON_PREFIX = "voz:"
AI_ERROR_TEXT = "Tuve un problema al consultar la IA. Inténtalo de nuevo en un momento."
UNEXPECTED_ERROR_TEXT = "Algo salió mal al procesar tu mensaje. Inténtalo de nuevo."
ASK_AGAIN_TEXT = "Responde con los botones, o escribe (o di en una nota de voz) «sí» o «no»."
EXPIRED_TEXT = "Esta pregunta ya expiró."
APPROVED_MARK = "✅ Confirmado"
REJECTED_MARK = "❌ Cancelado"
TIMEOUT_MARK = "⌛ Sin respuesta: cancelado"

COMMANDS = {
    "start": "Empezar",
    "nuevo": "Conversación nueva",
    "voz": "Elegir cuándo responder con voz",
    "memoria": "Ver lo que JARVIS recuerda de ti",
    "ayuda": "Ver la ayuda",
}

logger = logging.getLogger("jarvis.chat")
# Sin registro configurado (por ejemplo, en `telegram-vincular`), no se imprime nada extra.
logger.addHandler(logging.NullHandler())


class ChannelError(Exception):
    """Fallo del canal al enviar o recibir. El mensaje está pensado para el usuario."""


@dataclass(frozen=True)
class VoiceNote:
    ref: str  # identificador del audio en el canal (en Telegram, su file_id)
    duration: int  # segundos


@dataclass(frozen=True)
class IncomingMessage:
    id: str
    sender: str  # identificador del chat del usuario en el canal
    text: str | None  # None si no es texto (nota de voz, imagen…)
    voice: VoiceNote | None = None
    transcribed: bool = False  # el texto ya viene de la voz (por ejemplo, del micrófono del PC)


@dataclass(frozen=True)
class ButtonAnswer:
    id: str  # identificador del clic (el canal lo usa para acusar recibo)
    sender: str
    data: str  # dato del botón, por ejemplo "<id de la confirmación>:si"
    handle: Any = None  # mensaje que tenía el botón (para editarlo después)


ChatEvent = IncomingMessage | ButtonAnswer


class ChatChannel(Protocol):
    """Lo que el chat necesita de un canal de mensajería."""

    name: str

    def send_text(self, to: str, text: str) -> None: ...

    def show_typing(self, to: str) -> None: ...

    def send_with_buttons(self, to: str, text: str, buttons: list[tuple[str, str]]) -> Any:
        """Envía un mensaje con botones (texto, dato) y devuelve un identificador del mensaje."""
        ...

    def replace_message(self, to: str, handle: Any, text: str) -> None:
        """Reemplaza el texto de un mensaje enviado y quita sus botones."""
        ...

    def acknowledge(self, answer: ButtonAnswer, text: str = "") -> None: ...

    def download_voice(self, note: VoiceNote) -> bytes:
        """Descarga el audio de una nota de voz (solo a memoria)."""
        ...

    def send_voice(self, to: str, audio: bytes) -> None:
        """Envía una nota de voz (OGG/Opus)."""
        ...


# Crea el agente de un mensaje a partir del historial, el system prompt y el confirmador.
AgentFactory = Callable[[list, str, Confirmer], Agent]

# Atiende botones que no son de una confirmación (por ejemplo, los de un recordatorio).
# Devuelve False si el botón no es suyo.
ButtonHandler = Callable[[ButtonAnswer], bool]


class ChatService:
    def __init__(
        self,
        *,
        channel: ChatChannel,
        store: ConversationStore,
        agent_factory: AgentFactory,
        system_prompt: Callable[[], str],
        now: Callable[[], datetime],
        confirmation_timeout: float = CONFIRMATION_TIMEOUT_SECONDS,
        button_handler: ButtonHandler | None = None,
        transcriber: Transcriber | None = None,
        speaker: Speaker | None = None,
        memories: MemoryStore | None = None,
        purges: Sequence[Callable[[], int]] = (),
    ) -> None:
        """`purges`: limpiezas diarias adicionales (por ejemplo, pendientes hechos hace tiempo)."""
        self._channel = channel
        self._button_handler = button_handler
        self._transcriber = transcriber
        self._speaker = speaker
        self._memories = memories
        self._purges = purges
        self._speech_warned = False  # el aviso de "voz no disponible" se envía una sola vez
        self._store = store
        self._agent_factory = agent_factory
        self._system_prompt = system_prompt
        self._now = now
        self._confirmation_timeout = confirmation_timeout
        self._inbox: queue.Queue[ChatEvent] = queue.Queue()
        self._last_purge: datetime | None = None

    def submit(self, event: ChatEvent) -> None:
        """Encola un evento del usuario y vuelve de inmediato."""
        self._inbox.put(event)

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._run_forever, name="jarvis-chat", daemon=True)
        thread.start()
        return thread

    def process_next(self, timeout: float | None = None) -> bool:
        """Procesa un evento de la cola. Devuelve False si no llegó ninguno a tiempo."""
        try:
            event = self._inbox.get(timeout=timeout)
        except queue.Empty:
            return False
        self._purge_if_due()
        try:
            if isinstance(event, ButtonAnswer):
                self._handle_other_button(event)
            else:
                self._handle_message(event)
        except ChannelError as exc:
            logger.error("No se pudo responder al evento %s: %s", event.id, exc)
        except Exception:
            logger.exception("Error inesperado con el evento %s.", event.id)
            self._send_safely(event.sender, UNEXPECTED_ERROR_TEXT)
        return True

    def _run_forever(self) -> None:
        while True:
            self.process_next()

    def _handle_message(self, message: IncomingMessage) -> None:
        text = self._read_text(message)
        if text is None:
            return

        command = text.strip().lower().split("@")[0]  # "/ayuda@MiBot" → "/ayuda"
        if command == "/start":
            self._channel.send_text(message.sender, WELCOME_TEXT)
            return
        if command == "/nuevo":
            self._store.close_active(self._channel.name, message.sender)
            self._channel.send_text(message.sender, NEW_CONVERSATION_TEXT)
            return
        if command == "/ayuda":
            self._channel.send_text(message.sender, HELP_TEXT)
            return
        if command == "/voz":
            self._ask_voice_mode(message.sender)
            return
        if command == "/memoria" and self._memories is not None:
            self._channel.send_text(message.sender, self._memories_text())
            return

        self._show_typing(message.sender)
        conversation = self._store.load_active(self._channel.name, message.sender, self._system_prompt)
        # La fecha va en cada mensaje: el system prompt no cambia dentro de una conversación.
        # La marca de nota de voz avisa al modelo de que el texto puede traer errores de transcripción.
        mark = f"{VOICE_MARK} " if message.voice is not None or message.transcribed else ""
        reply = self._ask_agent(conversation, message.sender, f"[{self._now():%Y-%m-%d %H:%M}] {mark}{text}")
        if self._should_speak(message.sender, by_voice=message.voice is not None):
            self._send_voice_safely(message.sender, reply)
        self._channel.send_text(message.sender, reply)  # el texto llega siempre, también con voz
        logger.info("Mensaje %s respondido.", message.id)

    def _read_text(self, message: IncomingMessage) -> str | None:
        """Texto del mensaje (transcrito si es una nota de voz). None si no hay, tras avisar al usuario."""
        if message.voice is not None:
            return self._transcribe(message.sender, message.voice)
        if message.text is None:
            self._channel.send_text(message.sender, ONLY_TEXT_TEXT)
        return message.text

    def _transcribe(self, sender: str, note: VoiceNote) -> str | None:
        if self._transcriber is None:
            self._channel.send_text(sender, VOICE_DISABLED_TEXT)
            return None
        if note.duration > MAX_VOICE_SECONDS:
            self._channel.send_text(sender, VOICE_TOO_LONG_TEXT)
            return None

        self._show_typing(sender)
        try:
            audio = self._channel.download_voice(note)
        except ChannelError as exc:
            logger.error("No se pudo descargar una nota de voz: %s", exc)
            self._channel.send_text(sender, VOICE_DOWNLOAD_ERROR_TEXT)
            return None

        started = time.monotonic()
        try:
            text = self._transcriber.transcribe(audio)
        except TranscriptionError as exc:
            logger.error("Nota de voz sin transcribir: %s", exc)
            self._channel.send_text(sender, str(exc))
            return None
        # Solo duraciones: lo que se dijo nunca va al registro.
        logger.info("Nota de voz de %d s transcrita en %.1f s.", note.duration, time.monotonic() - started)

        if not text:
            self._channel.send_text(sender, VOICE_EMPTY_TEXT)
            return None
        self._channel.send_text(sender, HEARD_TEMPLATE.format(text))
        return text

    def _memories_text(self) -> str:
        """Lo que JARVIS recuerda, sin pasar por la IA."""
        assert self._memories is not None
        memories = self._memories.all()
        if not memories:
            return NO_MEMORIES_TEXT
        lines = "\n".join(f"{memory.id}. {memory.text}" for memory in memories)
        return f"Esto es lo que recuerdo de ti:\n\n{lines}\n\n{MEMORIES_FOOTER.format(id=memories[0].id)}"

    def _should_speak(self, sender: str, by_voice: bool) -> bool:
        if self._speaker is None:
            return False
        mode = self._voice_mode(sender)
        return mode == "siempre" or (mode == "espejo" and by_voice)

    def _voice_mode(self, sender: str) -> str:
        mode = self._store.get_preference(self._channel.name, sender, VOICE_PREFERENCE)
        return mode if mode in VOICE_MODES else DEFAULT_VOICE_MODE

    def _send_voice_safely(self, to: str, text: str) -> None:
        """La voz es un extra: si falla, la respuesta llega igual por escrito."""
        assert self._speaker is not None
        self._show_typing(to)
        try:
            started = time.monotonic()
            audio = self._speaker.speak(text)
            logger.info("Respuesta con voz generada en %.1f s.", time.monotonic() - started)
            self._channel.send_voice(to, audio)
        except SpeechUnavailableError as exc:
            logger.warning("Respuesta sin voz: %s", exc)
            if not self._speech_warned:
                self._speech_warned = True
                self._channel.send_text(to, str(exc))
        except (SpeechError, ChannelError) as exc:
            logger.warning("No se pudo enviar la respuesta con voz: %s", exc)

    def _ask_voice_mode(self, sender: str) -> None:
        if self._speaker is None:
            self._channel.send_text(sender, SPEECH_DISABLED_TEXT)
            return
        current = VOICE_MODES[self._voice_mode(sender)][1]
        buttons = [(label, f"{VOICE_BUTTON_PREFIX}{mode}") for mode, (label, *_) in VOICE_MODES.items()]
        self._channel.send_with_buttons(
            sender, f"¿Cuándo quieres que te responda con voz? Ahora: {current}.", buttons
        )

    def _handle_voice_button(self, answer: ButtonAnswer) -> None:
        mode = answer.data.removeprefix(VOICE_BUTTON_PREFIX)
        if mode not in VOICE_MODES:
            self._channel.acknowledge(answer, EXPIRED_TEXT)
            return
        self._store.set_preference(self._channel.name, answer.sender, VOICE_PREFERENCE, mode)
        self._channel.acknowledge(answer)
        self._close_safely(answer.sender, answer.handle, VOICE_MODES[mode][2])

    def _ask_agent(self, conversation: Conversation, sender: str, text: str) -> str:
        agent = self._agent_factory(conversation.messages, conversation.system_prompt, self._confirmer_for(sender))
        started = time.monotonic()
        try:
            reply = agent.send(text)
            # Solo el tiempo (incluye las tools y las confirmaciones): sirve para ver dónde se demora.
            logger.info("Respuesta de la IA en %.1f s.", time.monotonic() - started)
            return reply
        except anthropic.APIError as exc:
            logger.error("Error de la API de Anthropic (%s).", type(exc).__name__)
            return AI_ERROR_TEXT
        finally:
            conversation.messages = agent.history
            self._store.save(conversation)

    def _confirmer_for(self, sender: str) -> Confirmer:
        def confirm(prompt: str) -> bool:
            confirmation_id = uuid.uuid4().hex[:12]
            buttons = [("✅ Sí", f"{confirmation_id}:si"), ("❌ No", f"{confirmation_id}:no")]
            handle = self._channel.send_with_buttons(sender, prompt, buttons)
            approved = self._wait_for_answer(confirmation_id)
            mark = {True: APPROVED_MARK, False: REJECTED_MARK, None: TIMEOUT_MARK}[approved]
            self._close_safely(sender, handle, f"{prompt}\n\n{mark}")
            if approved is not None:
                self._show_typing(sender)
            return bool(approved)

        return confirm

    def _wait_for_answer(self, confirmation_id: str) -> bool | None:
        """Espera un botón de esta pregunta o un «s/n» escrito o dicho. None si se agota el tiempo."""
        deadline = self._now() + timedelta(seconds=self._confirmation_timeout)
        while True:
            remaining = (deadline - self._now()).total_seconds()
            try:
                if remaining <= 0:
                    raise queue.Empty
                event = self._inbox.get(timeout=remaining)
            except queue.Empty:
                return None

            if isinstance(event, ButtonAnswer):
                answer_id, _, value = event.data.partition(":")
                if answer_id != confirmation_id:
                    self._handle_other_button(event)
                    continue
                self._channel.acknowledge(event)
                return value == "si"

            text = self._read_text(event)  # una nota de voz con "sí" también vale
            if text is None:
                continue
            answer = parse_yes_no(text)
            if answer is not None:
                return answer
            self._channel.send_text(event.sender, ASK_AGAIN_TEXT)

    def _handle_other_button(self, answer: ButtonAnswer) -> None:
        """Botón que no responde a la confirmación en curso: de otra función o de una pregunta vieja."""
        if answer.data.startswith(VOICE_BUTTON_PREFIX):
            self._handle_voice_button(answer)
            return
        if self._button_handler is not None and self._button_handler(answer):
            return
        self._channel.acknowledge(answer, EXPIRED_TEXT)

    def _purge_if_due(self) -> None:
        now = self._now()
        if self._last_purge is None or now - self._last_purge >= PURGE_INTERVAL:
            deleted = self._store.purge_old()
            self._last_purge = now
            if deleted:
                logger.info("Borradas %d conversaciones antiguas.", deleted)
            for purge in self._purges:
                purge()

    def _show_typing(self, to: str) -> None:
        """Mostrar "escribiendo…" es cosmético: si falla, se sigue."""
        try:
            self._channel.show_typing(to)
        except ChannelError as exc:
            logger.warning("No se pudo mostrar 'escribiendo': %s", exc)

    def _close_safely(self, to: str, handle: Any, text: str) -> None:
        try:
            self._channel.replace_message(to, handle, text)
        except ChannelError as exc:
            logger.warning("No se pudo cerrar la pregunta de confirmación: %s", exc)

    def _send_safely(self, to: str, text: str) -> None:
        try:
            self._channel.send_text(to, text)
        except ChannelError as exc:
            logger.error("Tampoco se pudo enviar el aviso de error: %s", exc)


def split_text(text: str, limit: int) -> list[str]:
    """Divide un texto largo, preferentemente por párrafos, luego líneas y luego espacios."""
    text = text.strip() or "(sin respuesta)"
    chunks: list[str] = []
    while len(text) > limit:
        cut = next(
            (pos for sep in ("\n\n", "\n", " ") if (pos := text.rfind(sep, 0, limit)) > 0), limit
        )
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    chunks.append(text)
    return chunks
