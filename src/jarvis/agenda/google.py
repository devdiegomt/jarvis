"""Fuente de calendario real: Google Calendar (solo lectura)."""

from collections.abc import Callable
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Any

import httplib2
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from jarvis.agenda.base import CalendarError, CalendarNotAuthorizedError, Meeting
from jarvis.google_auth import (
    CALENDAR_SCOPE,
    LOGIN_HINT,
    GoogleAuthError,
    GoogleNotAuthorizedError,
    load_credentials,
)

MAX_ATTENDEES = 10

# Devuelve un cliente de la Calendar API v3 (o un doble en los tests).
ServiceFactory = Callable[[], Any]


def google_service_factory(token_file: Path) -> ServiceFactory:
    def factory() -> Any:
        credentials = load_credentials(token_file, [CALENDAR_SCOPE])
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

    def _fetch_events(self, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        page_token: str | None = None
        try:
            while True:
                response = (
                    self._get_service()
                    .events()
                    .list(
                        calendarId=self._calendar_id,
                        timeMin=time_min.isoformat(),
                        timeMax=time_max.isoformat(),
                        singleEvents=True,  # expande los eventos recurrentes
                        orderBy="startTime",
                        pageToken=page_token,
                    )
                    .execute()
                )
                events.extend(response.get("items", []))
                page_token = response.get("nextPageToken")
                if not page_token:
                    return events
        except HttpError as exc:
            raise self._http_error(exc) from exc
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

    def _http_error(self, exc: HttpError) -> CalendarError:
        status = exc.resp.status
        if status == 401:
            return CalendarNotAuthorizedError(f"La autorización de Google no es válida. {LOGIN_HINT}")
        if status == 404:
            return CalendarError(f"No encontré el calendario '{self._calendar_id}' (GOOGLE_CALENDAR_ID).")
        if status == 403:
            return CalendarError(
                "Google denegó el acceso al calendario. Revisa que la Calendar API esté activada "
                "en tu proyecto de Google Cloud."
            )
        return CalendarError(f"Google Calendar respondió con un error ({status}).")


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
