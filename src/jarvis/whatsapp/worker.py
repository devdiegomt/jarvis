"""Procesa en segundo plano los mensajes de WhatsApp, de uno en uno y en orden."""

import logging
import queue
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

import anthropic

from jarvis.agent import Agent
from jarvis.confirmation import CONFIRMATION_QUESTION, parse_yes_no
from jarvis.memory import Conversation, ConversationStore
from jarvis.tools import Confirmer
from jarvis.whatsapp.client import WhatsAppClient, WhatsAppError
from jarvis.whatsapp.webhook import IncomingMessage

CHANNEL = "whatsapp"
CONFIRMATION_TIMEOUT_SECONDS = 5 * 60
PURGE_INTERVAL = timedelta(hours=24)

HELP_TEXT = (
    "Soy JARVIS. Pregúntame por tu agenda o pídeme ayuda con tu día.\n\n"
    "Comandos:\n/nuevo: empezar una conversación nueva\n/ayuda: ver este mensaje"
)
NEW_CONVERSATION_TEXT = "Listo, empezamos una conversación nueva."
ONLY_TEXT_TEXT = "Por ahora solo entiendo mensajes de texto."
AI_ERROR_TEXT = "Tuve un problema al consultar la IA. Inténtalo de nuevo en un momento."
UNEXPECTED_ERROR_TEXT = "Algo salió mal al procesar tu mensaje. Inténtalo de nuevo."
CONFIRMATION_TIMEOUT_TEXT = "No recibí respuesta, así que cancelé la acción."

# Crea el agente de un mensaje a partir del historial, el system prompt y el confirmador.
AgentFactory = Callable[[list, str, Confirmer], Agent]

logger = logging.getLogger("jarvis.whatsapp")


class WhatsAppWorker:
    def __init__(
        self,
        *,
        client: WhatsAppClient,
        store: ConversationStore,
        agent_factory: AgentFactory,
        system_prompt: Callable[[], str],
        now: Callable[[], datetime],
        confirmation_timeout: float = CONFIRMATION_TIMEOUT_SECONDS,
    ) -> None:
        self._client = client
        self._store = store
        self._agent_factory = agent_factory
        self._system_prompt = system_prompt
        self._now = now
        self._confirmation_timeout = confirmation_timeout
        self._inbox: queue.Queue[IncomingMessage] = queue.Queue()
        self._last_purge: datetime | None = None

    def submit(self, message: IncomingMessage) -> None:
        """Llamado desde el webhook: encola el mensaje y vuelve de inmediato."""
        self._inbox.put(message)

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._run_forever, name="jarvis-whatsapp-worker", daemon=True)
        thread.start()
        return thread

    def process_next(self, timeout: float | None = None) -> bool:
        """Procesa un mensaje de la cola. Devuelve False si no llegó ninguno a tiempo."""
        try:
            message = self._inbox.get(timeout=timeout)
        except queue.Empty:
            return False
        self._purge_if_due()
        try:
            self._handle(message)
        except WhatsAppError as exc:
            logger.error("No se pudo responder al mensaje %s: %s", message.id, exc)
        except Exception:
            logger.exception("Error inesperado con el mensaje %s.", message.id)
            self._reply_safely(message.sender, UNEXPECTED_ERROR_TEXT)
        return True

    def _run_forever(self) -> None:
        while True:
            self.process_next()

    def _handle(self, message: IncomingMessage) -> None:
        self._mark_read(message.id, show_typing=True)
        if message.text is None:
            self._client.send_text(message.sender, ONLY_TEXT_TEXT)
            return

        command = message.text.strip().lower()
        if command == "/nuevo":
            self._store.close_active(CHANNEL, message.sender)
            self._client.send_text(message.sender, NEW_CONVERSATION_TEXT)
            return
        if command == "/ayuda":
            self._client.send_text(message.sender, HELP_TEXT)
            return

        conversation = self._store.load_active(CHANNEL, message.sender, self._system_prompt)
        reply = self._ask_agent(conversation, message)
        self._client.send_text(message.sender, reply)
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
            self._client.send_text(sender, f"{prompt}\n\n{CONFIRMATION_QUESTION}")
            return self._wait_for_answer(sender)

        return confirm

    def _wait_for_answer(self, sender: str) -> bool:
        """Espera la respuesta s/n. El siguiente mensaje del usuario se toma como respuesta."""
        deadline = self._now() + timedelta(seconds=self._confirmation_timeout)
        while True:
            remaining = (deadline - self._now()).total_seconds()
            try:
                if remaining <= 0:
                    raise queue.Empty
                answer_message = self._inbox.get(timeout=remaining)
            except queue.Empty:
                self._client.send_text(sender, CONFIRMATION_TIMEOUT_TEXT)
                return False
            self._mark_read(answer_message.id, show_typing=False)
            answer = parse_yes_no(answer_message.text or "")
            if answer is not None:
                return answer
            self._client.send_text(sender, "Responde 's' o 'n'.")

    def _purge_if_due(self) -> None:
        now = self._now()
        if self._last_purge is None or now - self._last_purge >= PURGE_INTERVAL:
            deleted = self._store.purge_old()
            self._last_purge = now
            if deleted:
                logger.info("Borradas %d conversaciones antiguas.", deleted)

    def _mark_read(self, message_id: str, show_typing: bool) -> None:
        """Marcar como leído es cosmético: si falla, se sigue procesando el mensaje."""
        try:
            self._client.mark_read(message_id, show_typing=show_typing)
        except WhatsAppError as exc:
            logger.warning("No se pudo marcar el mensaje %s como leído: %s", message_id, exc)

    def _reply_safely(self, to: str, text: str) -> None:
        try:
            self._client.send_text(to, text)
        except WhatsAppError as exc:
            logger.error("Tampoco se pudo enviar el aviso de error: %s", exc)
