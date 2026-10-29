"""Canal de notificación por Telegram (por ejemplo, para el resumen diario)."""

from jarvis.notify.base import NotificationError, NotificationNotAuthorizedError
from jarvis.telegram.bot import TelegramChannel
from jarvis.telegram.client import TelegramAuthError, TelegramClient, TelegramError


class TelegramNotifier:
    name = "Telegram"

    def __init__(self, client: TelegramClient, chat_id: str) -> None:
        self._channel = TelegramChannel(client)
        self._chat_id = chat_id

    def send(self, subject: str, body: str) -> None:
        try:
            self._channel.send_text(self._chat_id, f"{subject}\n\n{body}")
        except TelegramAuthError as exc:
            raise NotificationNotAuthorizedError(str(exc)) from exc
        except TelegramError as exc:
            raise NotificationError(str(exc)) from exc
