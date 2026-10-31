"""Fuente de calendario real: Google Calendar (leer, y agendar, mover y cancelar eventos propios).

Al escribir nunca se envían invitaciones ni avisos a otras personas (`sendUpdates="none"`).
"""

from collections.abc import Callable
from datetime import date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

import httplib2
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from jarvis.agenda.base import CalendarError, CalendarNotAuthorizedError, Meeting
from jarvis.google_auth import (
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_SCOPE,
    LOGIN_HINT,
    GoogleAuthError,
    GoogleNotAuthorizedError,
    load_credentials,
)

MAX_ATTENDEES = 10

# Devuelve un cliente de la Calendar API v3 (o un doble en los tests).
ServiceFactory = Callable[[], Any]


WRITE_PERMISSION_HINT = (
    "JARVIS todavía no tiene permiso para editar tu calendario (solo para leerlo). "
    "Ejecuta `uv run python -m jarvis google-login` en el PC y acepta el nuevo permiso."
)


def google_service_factory(token_file: Path) -> ServiceFactory:
    def factory() -> Any:
        # Basta con poder leer: con el permiso antiguo (solo lectura) JARVIS sigue mostrando la
        # agenda, y al intentar escribir explica cómo dar el permiso nuevo.
        credentials = load_credentials(token_file, [])
        if not {CALENDAR_EVENTS_SCOPE, CALENDAR_SCOPE} & set(credentials.scopes or []):
            raise GoogleNotAuthorizedError(f"La autorización de Google no incluye el calendario. {LOGIN_HINT}")
        return build("calendar", "v3", credentials=credentials, cache_discovery=False)

    return factory


class GoogleCalendar:
    name = "Google Calendar"

    def __init__(self, service_factory: ServiceFactory, calendar_id: str, timezone: tzinfo) -> None:
        self._service_factory = service_factory
        self._service: Any = None
        self._calendar_id = calendar_id
        self._tz = timezone

    def list_meetings(self, start: date, end: date) -> list[Meeting]:
        events = self._fetch_events(
            time_min=datetime.combine(start, time.min, self._tz),
            time_max=datetime.combine(end + timedelta(days=1), time.min, self._tz),
        )
        meetings = (to_meeting(event, self._tz) for event in events)
        return [meeting for meeting in meetings if meeting is not None]

    def get_event(self, event_id: str) -> Meeting | None:
        try:
            event = self._call(
                lambda events: events.get(calendarId=self._calendar_id, eventId=event_id), about_event=True
            )
        except EventNotFoundError:
            return None
        return to_meeting(event, self._tz)

    def create_event(
        self, title: str, start: datetime, end: datetime, location: str | None, description: str | None
    ) -> Meeting:
        body: dict[str, Any] = {
            "summary": title,
            "start": self._when(start),
            "end": self._when(end),
            # Marca los eventos creados por JARVIS (visible solo para el usuario).
            "extendedProperties": {"private": {"jarvis": "1"}},
        }
        if location:
            body["location"] = location
        if description:
            body["description"] = description
        event = self._call(
            lambda events: events.insert(calendarId=self._calendar_id, body=body, sendUpdates="none")
        )
        return self._as_meeting(event)

    def move_event(self, event_id: str, start: datetime, end: datetime) -> Meeting:
        body = {"start": self._when(start), "end": self._when(end)}
        event = self._call(
            lambda events: events.patch(
                calendarId=self._calendar_id, eventId=event_id, body=body, sendUpdates="none"
            ),
            about_event=True,
        )
        return self._as_meeting(event)

    def delete_event(self, event_id: str) -> None:
        self._call(
            lambda events: events.delete(calendarId=self._calendar_id, eventId=event_id, sendUpdates="none"),
            about_event=True,
        )

    def _when(self, moment: datetime) -> dict[str, str]:
        when = {"dateTime": moment.isoformat()}
        if isinstance(self._tz, ZoneInfo):
            when["timeZone"] = self._tz.key
        return when

    def _as_meeting(self, event: dict[str, Any]) -> Meeting:
        meeting = to_meeting(event, self._tz)
        if meeting is None:
            raise CalendarError("Google Calendar no devolvió el evento.")
        return meeting

    def _fetch_events(self, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            response = self._call(
                lambda api: api.list(
                    calendarId=self._calendar_id,
                    timeMin=time_min.isoformat(),
                    timeMax=time_max.isoformat(),
                    singleEvents=True,  # expande los eventos recurrentes
                    orderBy="startTime",
                    pageToken=page_token,
                )
            )
            events.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return events

    def _call(self, request: Callable[[Any], Any], about_event: bool = False) -> Any:
        """Ejecuta una petición sobre `events()` y traduce los errores a mensajes para el usuario.

        `about_event`: la petición es sobre un evento concreto (un 404 significa que no existe).
        """
        try:
            return request(self._get_service().events()).execute()
        except HttpError as exc:
            raise self._http_error(exc, about_event) from exc
        except GoogleNotAuthorizedError as exc:
            raise CalendarNotAuthorizedError(str(exc)) from exc
        except GoogleAuthError as exc:
            raise CalendarError(str(exc)) from exc
        except RefreshError as exc:
            raise CalendarNotAuthorizedError(
                f"Google rechazó la autorización (pudo ser revocada). {LOGIN_HINT}"
            ) from exc
        except (TransportError, httplib2.HttpLib2Error, OSError) as exc:
            raise CalendarError("No pude conectar con Google Calendar.") from exc

    def _get_service(self) -> Any:
        if self._service is None:
            self._service = self._service_factory()
        return self._service

    def _http_error(self, exc: HttpError, about_event: bool = False) -> CalendarError:
        status = exc.resp.status
        if status == 401:
            return CalendarNotAuthorizedError(f"La autorización de Google no es válida. {LOGIN_HINT}")
        if about_event and status in (404, 410):
            return EventNotFoundError("No encontré ese evento en el calendario (pudo cancelarse antes).")
        if status == 404:
            return CalendarError(f"No encontré el calendario '{self._calendar_id}' (GOOGLE_CALENDAR_ID).")
        if status == 403 and "insufficient" in str(exc).lower():
            return CalendarNotAuthorizedError(WRITE_PERMISSION_HINT)
        if status == 403:
            return CalendarError(
                "Google denegó el acceso al calendario. Revisa que la Calendar API esté activada "
                "en tu proyecto de Google Cloud."
            )
        return CalendarError(f"Google Calendar respondió con un error ({status}).")


class EventNotFoundError(CalendarError):
    """El evento no existe (o ya se canceló)."""


def to_meeting(event: dict[str, Any], timezone: tzinfo) -> Meeting | None:
    """Convierte un evento de la API en `Meeting`. Devuelve None si no debe mostrarse."""
    if event.get("status") == "cancelled" or _declined_by_me(event):
        return None

    start, end = event["start"], event["end"]
    attendees = tuple(
        attendee.get("displayName") or attendee["email"]
        for attendee in event.get("attendees", [])
        if not attendee.get("self") and not attendee.get("resource") and "email" in attendee
    )[:MAX_ATTENDEES]
    common = {
        "title": event.get("summary") or "(Sin título)",
        "location": event.get("location"),
        "attendees": attendees,
        "id": event.get("id"),
        # Las invitaciones de otras personas no se mueven ni se cancelan desde JARVIS.
        "organized_by_me": bool(event.get("organizer", {}).get("self", False)),
        "recurring": "recurringEventId" in event,
    }

    if "dateTime" in start:
        return Meeting(
            start=datetime.fromisoformat(start["dateTime"]).astimezone(timezone),
            end=datetime.fromisoformat(end["dateTime"]).astimezone(timezone),
            **common,
        )
    # Día completo: Google da la fecha de fin exclusiva; la guardamos inclusiva.
    return Meeting(
        start=date.fromisoformat(start["date"]),
        end=date.fromisoformat(end["date"]) - timedelta(days=1),
        all_day=True,
        **common,
    )


def _declined_by_me(event: dict[str, Any]) -> bool:
    return any(
        attendee.get("self") and attendee.get("responseStatus") == "declined"
        for attendee in event.get("attendees", [])
    )
