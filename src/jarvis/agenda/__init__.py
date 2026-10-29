"""Fuentes de calendario de JARVIS (ejemplo y Google Calendar)."""

from jarvis.agenda.base import CalendarError, CalendarNotAuthorizedError, CalendarSource, Meeting
from jarvis.agenda.sample import SampleCalendar
from jarvis.config import ConfigError, Settings


def build_calendar(settings: Settings) -> CalendarSource:
    """Crea la fuente de calendario elegida en JARVIS_CALENDAR."""
    if settings.calendar_source == "sample":
        return SampleCalendar(settings.timezone)

    # Importación diferida: las librerías de Google solo se cargan si se usan.
    from jarvis.agenda.google import GoogleCalendar, google_service_factory

    token_file = settings.google.token_file
    if not token_file.exists():
        raise ConfigError(
            "JARVIS_CALENDAR=google pero Google Calendar no está autorizado. "
            "Ejecuta `uv run jarvis google-login` primero."
        )
    return GoogleCalendar(
        service_factory=google_service_factory(token_file),
        calendar_id=settings.google.calendar_id,
        timezone=settings.timezone,
    )


__all__ = [
    "CalendarError",
    "CalendarNotAuthorizedError",
    "CalendarSource",
    "Meeting",
    "SampleCalendar",
    "build_calendar",
]
