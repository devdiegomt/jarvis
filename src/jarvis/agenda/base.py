"""Tipos comunes a todas las fuentes de calendario."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol


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


def meeting_to_dict(meeting: Meeting) -> dict[str, Any]:
    """Representación JSON de una reunión, pensada para el modelo."""
    if meeting.all_day:
        start, end = meeting.start.isoformat(), meeting.end.isoformat()
    else:
        start, end = (f"{dt:%Y-%m-%d %H:%M}" for dt in (meeting.start, meeting.end))
    data: dict[str, Any] = {
        "titulo": meeting.title,
        "inicio": start,
        "fin": end,
        "todo_el_dia": meeting.all_day,
    }
    if meeting.location:
        data["ubicacion"] = meeting.location
    if meeting.attendees:
        data["participantes"] = list(meeting.attendees)
    return data


def meeting_to_line(meeting: Meeting) -> str:
    """Una línea de texto legible, por ejemplo: `09:30-10:00  Demo (con Ana) · Sala 1`."""
    when = "Todo el día" if meeting.all_day else f"{meeting.start:%H:%M}-{meeting.end:%H:%M}"
    line = f"{when}  {meeting.title}"
    if meeting.attendees:
        line += f" (con {', '.join(meeting.attendees)})"
    if meeting.location:
        line += f" · {meeting.location}"
    return line
