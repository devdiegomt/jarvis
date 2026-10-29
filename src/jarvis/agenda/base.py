"""Tipos comunes a todas las fuentes de calendario."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


class CalendarError(Exception):
    """Fallo al consultar el calendario. El mensaje está pensado para el usuario."""


class CalendarNotAuthorizedError(CalendarError):
    """No hay autorización válida para leer el calendario."""


@dataclass(frozen=True)
class Meeting:
    """Una reunión o evento.

    Para eventos de día completo, `start` y `end` son fechas (`end` inclusiva).
    Para eventos con hora, son datetimes en la zona horaria del usuario.
    """

    title: str
    start: datetime | date
    end: datetime | date
    all_day: bool = False
    location: str | None = None
    attendees: tuple[str, ...] = ()


class CalendarSource(Protocol):
    """Interfaz que cumplen todas las fuentes de calendario."""

    name: str

    def list_meetings(self, start: date, end: date) -> list[Meeting]:
        """Reuniones entre `start` y `end` (ambas fechas incluidas), ordenadas por inicio."""
        ...
