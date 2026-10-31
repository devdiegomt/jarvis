"""Calendario de ejemplo con datos simulados (sin conexión a ningún servicio).

Admite agendar, mover y cancelar en memoria (se pierde al cerrar JARVIS), para probar sin tocar
un calendario real.
"""

import uuid
from dataclasses import replace
from datetime import date, datetime, time, timedelta, tzinfo

from jarvis.agenda.base import CalendarError, Meeting

# (hora, duración en minutos, título, participante, lo organizo yo)
_WEEKDAY_MEETINGS: list[tuple[time, int, str, str, bool]] = [
    (time(9, 30), 30, "Daily del equipo", "Equipo de producto", True),
    (time(12, 0), 60, "Revisión de propuesta del cliente", "Laura Gómez", False),
    (time(16, 30), 45, "Planificación semanal", "Carlos Ruiz", True),
]


class SampleCalendar:
    name = "ejemplo (datos simulados)"

    def __init__(self, timezone: tzinfo) -> None:
        self._tz = timezone
        # Cambios en memoria: id → evento (movido o creado), o None si se canceló.
        self._changes: dict[str, Meeting | None] = {}

    def list_meetings(self, start: date, end: date) -> list[Meeting]:
        meetings: list[Meeting] = []
        day = start
        while day <= end:
            meetings.extend(m for m in self._meetings_for(day) if m.id not in self._changes)
            day += timedelta(days=1)
        meetings += [m for m in self._changes.values() if m is not None and start <= _day_of(m) <= end]
        return sorted(meetings, key=_start_key)

    def get_event(self, event_id: str) -> Meeting | None:
        if event_id in self._changes:
            return self._changes[event_id]
        try:
            day = date.fromisoformat(event_id.split("_")[1])
        except (IndexError, ValueError):
            return None
        return next((m for m in self._meetings_for(day) if m.id == event_id), None)

    def create_event(
        self, title: str, start: datetime, end: datetime, location: str | None, description: str | None
    ) -> Meeting:
        event_id = f"nuevo_{uuid.uuid4().hex[:8]}"
        meeting = Meeting(title=title, start=start, end=end, location=location, id=event_id)
        self._changes[event_id] = meeting
        return meeting

    def move_event(self, event_id: str, start: datetime, end: datetime) -> Meeting:
        meeting = self._existing(event_id)
        moved = replace(meeting, start=start, end=end)
        self._changes[event_id] = moved
        return moved

    def delete_event(self, event_id: str) -> None:
        self._existing(event_id)
        self._changes[event_id] = None

    def _existing(self, event_id: str) -> Meeting:
        meeting = self.get_event(event_id)
        if meeting is None:
            raise CalendarError("No encontré ese evento en el calendario.")
        return meeting

    def _meetings_for(self, day: date) -> list[Meeting]:
        # Los fines de semana hay menos reuniones, para que los datos parezcan realistas.
        templates = _WEEKDAY_MEETINGS[1:] if day.weekday() >= 5 else _WEEKDAY_MEETINGS
        meetings = []
        for index, (start_time, minutes, title, attendee, mine) in enumerate(templates):
            start = datetime.combine(day, start_time, self._tz)
            meetings.append(
                Meeting(
                    title=title,
                    start=start,
                    end=start + timedelta(minutes=minutes),
                    attendees=(attendee,),
                    id=f"ejemplo_{day.isoformat()}_{index}",
                    organized_by_me=mine,
                )
            )
        return meetings


def _start_key(meeting: Meeting) -> tuple[date, time]:
    """Para ordenar por inicio: los de día completo, primero."""
    return _day_of(meeting), meeting.start.time() if isinstance(meeting.start, datetime) else time.min


def _day_of(meeting: Meeting) -> date:
    return meeting.start.date() if isinstance(meeting.start, datetime) else meeting.start
