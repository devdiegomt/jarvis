"""Tipos comunes a todos los canales de notificación."""

from typing import Protocol


class NotificationError(Exception):
    """Fallo al enviar una notificación. El mensaje está pensado para el usuario."""


class NotificationNotAuthorizedError(NotificationError):
    """El canal no tiene autorización válida (reintentar no sirve)."""


class Notifier(Protocol):
    """Canal por el que JARVIS envía mensajes al usuario."""

    name: str

    def send(self, subject: str, body: str) -> None: ...
