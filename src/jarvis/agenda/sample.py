"""Calendario de ejemplo con datos simulados (sin conexión a ningún servicio)."""

from datetime import date, datetime, time, timedelta, tzinfo

from jarvis.agenda.base import Meeting

# (hora, duración en minutos, título, participante)
_WEEKDAY_MEETINGS: list[tuple[time, int, str, str]] = [
    (time(9, 30), 30, "Daily del equipo", "Equipo de producto"),
    (time(12, 0), 60, "Revisión de propuesta", "Laura Gómez (cliente)"),
    (time(16, 30), 45, "Planificación semanal", "Carlos Ruiz"),
]


class SampleCalendar:
    name = "ejemplo (datos simulados)"

    def __init__(self, timezone: tzinfo) -> None:
        self._tz = timezone

    def list_meetings(self, start: date, end: date) -> list[Meeting]:
        meetings: list[Meeting] = []
        day = start
        while day <= end:
            meetings.extend(self._meetings_for(day))
            day += timedelta(days=1)
        return meetings

    def _meetings_for(self, day: date) -> list[Meeting]:
        # Los fines de semana hay menos reuniones, para que los datos parezcan realistas.
        templates = _WEEKDAY_MEETINGS[1:] if day.weekday() >= 5 else _WEEKDAY_MEETINGS
        meetings = []
        for start_time, minutes, title, attendee in templates:
            start = datetime.combine(day, start_time, self._tz)
            meetings.append(
                Meeting(
                    title=title,
                    start=start,
                    end=start + timedelta(minutes=minutes),
                    attendees=(attendee,),
                )
            )
        return meetings
