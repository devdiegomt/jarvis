"""Chat con JARVIS por un canal de mensajería, independiente del canal concreto (hoy Telegram).

El servicio procesa los eventos de uno en uno y en orden en un único hilo. Eso permite que
una confirmación espere la respuesta leyendo la misma cola: el siguiente evento del usuario
(un botón o un "s/n" escrito) es la respuesta.
"""

import logging
import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

import anthropic

from jarvis.agent import Agent
from jarvis.confirmation import parse_yes_no
from jarvis.memory import Conversation, ConversationStore
from jarvis.tools import Confirmer

CONFIRMATION_TIMEOUT_SECONDS = 5 * 60
PURGE_INTERVAL = timedelta(hours=24)

WELCOME_TEXT = (
    "Hola, soy JARVIS. Pregúntame por tu agenda o pídeme ayuda con tu día.\n\n"
    "Comandos: /nuevo para empezar una conversación nueva, /ayuda para ver esta ayuda."
)
HELP_TEXT = (
    "Pregúntame, por ejemplo: «¿Qué tengo hoy?» o «¿Tengo algo libre el jueves por la tarde?».\n\n"
    "/nuevo: empezar una conversación nueva\n/ayuda: ver esta ayuda"
)
NEW_CONVERSATION_TEXT = "Listo, empezamos una conversación nueva."
ONLY_TEXT_TEXT = "Por ahora solo entiendo mensajes de texto."
AI_ERROR_TEXT = "Tuve un problema al consultar la IA. Inténtalo de nuevo en un momento."
UNEXPECTED_ERROR_TEXT = "Algo salió mal al procesar tu mensaje. Inténtalo de nuevo."
ASK_AGAIN_TEXT = "Responde con los botones, o escribe «s» o «n»."
EXPIRED_TEXT = "Esta pregunta ya expiró."
APPROVED_MARK = "✅ Confirmado"
REJECTED_MARK = "❌ Cancelado"
TIMEOUT_MARK = "⌛ Sin respuesta: cancelado"

COMMANDS = {"start": "Empezar", "nuevo": "Conversación nueva", "ayuda": "Ver la ayuda"}

logger = logging.getLogger("jarvis.chat")
# Sin registro configurado (por ejemplo, en `telegram-vincular`), no se imprime nada extra.
logger.addHandler(logging.NullHandler())


class ChannelError(Exception):
    """Fallo del canal al enviar o recibir. El mensaje está pensado para el usuario."""


@dataclass(frozen=True)
class IncomingMessage:
    id: str
    sender: str  # identificador del chat del usuario en el canal
    text: str | None  # None si no es texto (audio, imagen…)


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
    ) -> None:
        self._channel = channel
        self._button_handler = button_handler
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
        if message.text is None:
            self._channel.send_text(message.sender, ONLY_TEXT_TEXT)
            return

        command = message.text.strip().lower().split("@")[0]  # "/ayuda@MiBot" → "/ayuda"
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

        self._show_typing(message.sender)
        conversation = self._store.load_active(self._channel.name, message.sender, self._system_prompt)
        reply = self._ask_agent(conversation, message)
        self._channel.send_text(message.sender, reply)
        logger.info("Mensaje %s respondido.", message.id)

    def _ask_agent(self, conversation: Conversation, message: IncomingMessage) -> str:
        agent = self._agent_factory(
            conversation.messages, conversation.system_prompt, self._confirmer_for(message.sender)
        )
        # La fecha va en cada mensaje: el system prompt no cambia dentro de una conversación.
        text = f"[{self._now():%Y-%m-%d %H:%M}] {message.text}"
        try:
            return agent.send(text)
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
        """Espera un botón de esta pregunta o un «s/n» escrito. None si se agota el tiempo."""
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

            answer = parse_yes_no(event.text or "")
            if answer is not None:
                return answer
            self._channel.send_text(event.sender, ASK_AGAIN_TEXT)

    def _handle_other_button(self, answer: ButtonAnswer) -> None:
        """Botón que no responde a la confirmación en curso: de otra función o de una pregunta vieja."""
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
