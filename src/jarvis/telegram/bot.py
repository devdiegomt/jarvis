"""Adaptador de Telegram para el chat: lectura de mensajes (long polling) y envío."""

import logging
import time
from collections.abc import Callable
from typing import Any

from jarvis.chat import ButtonAnswer, ChatEvent, IncomingMessage, split_text
from jarvis.telegram.client import TelegramClient, TelegramConflictError, TelegramConnectionError

CHANNEL_NAME = "telegram"
MAX_TEXT_LENGTH = 4096  # límite de Telegram por mensaje
MAX_BACKOFF_SECONDS = 60
CONFLICT_WAIT_SECONDS = 60

logger = logging.getLogger("jarvis.chat")


class TelegramChannel:
    """Implementa `ChatChannel` sobre la API de bots de Telegram."""

    name = CHANNEL_NAME

    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    def send_text(self, to: str, text: str) -> None:
        for chunk in split_text(text, MAX_TEXT_LENGTH):
            self._client.send_message(to, chunk)

    def show_typing(self, to: str) -> None:
        self._client.send_typing(to)

    def send_with_buttons(self, to: str, text: str, buttons: list[tuple[str, str]]) -> int:
        message = self._client.send_message(to, text, buttons=buttons)
        return int(message["message_id"])

    def replace_message(self, to: str, handle: int, text: str) -> None:
        self._client.edit_message_text(to, handle, text)

    def acknowledge(self, answer: ButtonAnswer, text: str = "") -> None:
        self._client.answer_callback(answer.id, text)


def parse_update(update: dict[str, Any], owner_id: str) -> ChatEvent | None:
    """Convierte una actualización de Telegram en un evento del chat.

    Solo se aceptan mensajes y botones del usuario dueño, en su chat privado con el bot.
    """
    if "message" in update:
        message = update["message"]
        chat, sender = message.get("chat", {}), message.get("from", {})
        if chat.get("type") != "private" or str(sender.get("id")) != owner_id:
            _log_ignored(sender)
            return None
        return IncomingMessage(
            id=f"{chat['id']}:{message['message_id']}", sender=str(chat["id"]), text=message.get("text")
        )

    if "callback_query" in update:
        callback = update["callback_query"]
        sender = callback.get("from", {})
        chat = callback.get("message", {}).get("chat", {})
        if str(sender.get("id")) != owner_id or chat.get("type") != "private":
            _log_ignored(sender)
            return None
        return ButtonAnswer(
            id=callback["id"],
            sender=str(chat["id"]),
            data=callback.get("data", ""),
            handle=callback.get("message", {}).get("message_id"),
        )

    return None


class TelegramPoller:
    """Pide a Telegram los mensajes nuevos (long polling) y los entrega al chat."""

    def __init__(
        self,
        client: TelegramClient,
        owner_id: str,
        deliver: Callable[[ChatEvent], None],
        mark_processed: Callable[[str], bool],
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._owner_id = owner_id
        self._deliver = deliver
        self._mark_processed = mark_processed
        self._sleep = sleep
        self._offset: int | None = None

    def poll_once(self) -> int:
        """Una consulta a Telegram. Devuelve cuántos eventos se entregaron al chat."""
        delivered = 0
        for update in self._client.get_updates(self._offset):
            self._offset = update["update_id"] + 1  # confirma la actualización en la siguiente consulta
            event = parse_update(update, self._owner_id)
            if event is None:
                continue
            # Tras un reinicio, Telegram reenvía lo que no se confirmó: se ignora lo ya procesado.
            if not self._mark_processed(f"{CHANNEL_NAME}:{update['update_id']}"):
                continue
            logger.info("Evento %s recibido.", event.id)
            self._deliver(event)
            delivered += 1
        return delivered

    def run_forever(self, wait_on_conflict: bool = False) -> None:
        """Consulta sin parar. Los fallos de red se reintentan con espera creciente.

        Si otra copia está leyendo el mismo bot, con `wait_on_conflict` (modo en segundo plano)
        se espera a que termine; si no, el error se propaga. Los demás errores (token inválido,
        certificado) siempre se propagan.
        """
        backoff = 1.0
        while True:
            try:
                self.poll_once()
                backoff = 1.0
            except TelegramConnectionError as exc:
                logger.warning("%s Reintento en %.0f s.", exc, backoff)
                self._sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            except TelegramConflictError:
                if not wait_on_conflict:
                    raise
                logger.warning(
                    "Otra copia de JARVIS está usando el bot. Reintento en %d s.", CONFLICT_WAIT_SECONDS
                )
                self._sleep(CONFLICT_WAIT_SECONDS)


def wait_for_first_message(
    client: TelegramClient,
    timeout_seconds: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    """Espera el primer mensaje privado al bot y devuelve quién lo envió (para vincular la cuenta).

    El mensaje se confirma a Telegram para que el chat no lo procese después.
    """
    deadline = clock() + timeout_seconds
    offset: int | None = None
    while clock() < deadline:
        try:
            updates = client.get_updates(offset)
        except TelegramConnectionError:
            sleep(2)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message", {})
            if message.get("chat", {}).get("type") != "private":
                continue
            client.get_updates(offset, timeout=0)
            client.send_message(str(message["chat"]["id"]), "Listo, te reconocí. Vuelve a la terminal.")
            return dict(message.get("from", {}))
    return None


def _log_ignored(sender: dict[str, Any]) -> None:
    logger.warning("Mensaje ignorado de un usuario no autorizado (ID %s).", sender.get("id"))
