from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httplib2
import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from jarvis.agenda import CalendarError, CalendarNotAuthorizedError
from jarvis.agenda.google import GoogleCalendar, to_meeting
from jarvis.google_auth import GoogleAuthError, GoogleNotAuthorizedError

BOGOTA = ZoneInfo("America/Bogota")  # UTC-5, sin horario de verano


class FakeRequest:
    def __init__(self, result: Any) -> None:
        self._result = result

    def execute(self) -> Any:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeEvents:
    def __init__(self, pages: list[Any]) -> None:
        self._pages = list(pages)
        self.calls: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> FakeRequest:
        self.calls.append(kwargs)
        return FakeRequest(self._pages.pop(0))


class FakeService:
    """Doble mínimo de la Calendar API: service.events().list(...).execute()."""

    def __init__(self, *pages: Any) -> None:
        self.events_resource = FakeEvents(list(pages))

    def events(self) -> FakeEvents:
        return self.events_resource


def make_calendar(service: FakeService) -> GoogleCalendar:
    return GoogleCalendar(service_factory=lambda: service, calendar_id="primary", timezone=BOGOTA)


def http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b"{}")


def timed_event(summary: str, start: str, end: str, **extra: Any) -> dict[str, Any]:
    return {"summary": summary, "start": {"dateTime": start}, "end": {"dateTime": end}, **extra}


# --- Consulta a la API ------------------------------------------------------


def test_requests_the_full_local_day_range() -> None:
    service = FakeService({"items": []})

    make_calendar(service).list_meetings(date(2026, 10, 29), date(2026, 10, 30))

    call = service.events_resource.calls[0]
    assert call["calendarId"] == "primary"
    assert call["timeMin"] == "2026-10-29T00:00:00-05:00"
    assert call["timeMax"] == "2026-10-31T00:00:00-05:00"
    assert call["singleEvents"] is True
    assert call["orderBy"] == "startTime"


def test_follows_pagination() -> None:
    service = FakeService(
        {"items": [timed_event("A", "2026-10-29T09:00:00-05:00", "2026-10-29T10:00:00-05:00")], "nextPageToken": "p2"},
        {"items": [timed_event("B", "2026-10-29T11:00:00-05:00", "2026-10-29T12:00:00-05:00")]},
    )

    meetings = make_calendar(service).list_meetings(date(2026, 10, 29), date(2026, 10, 29))

    assert [m.title for m in meetings] == ["A", "B"]
    assert service.events_resource.calls[1]["pageToken"] == "p2"


def test_service_is_created_once() -> None:
    created: list[FakeService] = []

    def factory() -> FakeService:
        created.append(FakeService({"items": []}, {"items": []}))
        return created[-1]

    calendar = GoogleCalendar(service_factory=factory, calendar_id="primary", timezone=BOGOTA)
    calendar.list_meetings(date(2026, 10, 29), date(2026, 10, 29))
    calendar.list_meetings(date(2026, 10, 30), date(2026, 10, 30))

    assert len(created) == 1


# --- Conversión de eventos --------------------------------------------------


def test_timed_event_is_converted_to_local_time() -> None:
    event = timed_event(
        "Demo",
        "2026-10-29T14:30:00Z",
        "2026-10-29T15:00:00Z",
        location="Meet",
        attendees=[
            {"email": "yo@example.com", "self": True, "responseStatus": "accepted"},
            {"email": "ana@example.com", "displayName": "Ana"},
            {"email": "luis@example.com"},
            {"email": "sala@resource.calendar.google.com", "resource": True},
        ],
    )

    meeting = to_meeting(event, BOGOTA)

    assert meeting is not None
    assert meeting.start == datetime(2026, 10, 29, 9, 30, tzinfo=BOGOTA)
    assert meeting.end == datetime(2026, 10, 29, 10, 0, tzinfo=BOGOTA)
    assert not meeting.all_day
    assert meeting.location == "Meet"
    assert meeting.attendees == ("Ana", "luis@example.com")


def test_all_day_event_has_inclusive_end_date() -> None:
    event = {"summary": "Vacaciones", "start": {"date": "2026-10-29"}, "end": {"date": "2026-10-31"}}

    meeting = to_meeting(event, BOGOTA)

    assert meeting is not None
    assert meeting.all_day
    assert (meeting.start, meeting.end) == (date(2026, 10, 29), date(2026, 10, 30))


def test_event_without_title_gets_placeholder() -> None:
    meeting = to_meeting(timed_event("", "2026-10-29T09:00:00-05:00", "2026-10-29T10:00:00-05:00"), BOGOTA)

    assert meeting is not None
    assert meeting.title == "(Sin título)"


def test_cancelled_and_declined_events_are_skipped() -> None:
    cancelled = timed_event("X", "2026-10-29T09:00:00-05:00", "2026-10-29T10:00:00-05:00", status="cancelled")
    declined = timed_event(
        "Y",
        "2026-10-29T09:00:00-05:00",
        "2026-10-29T10:00:00-05:00",
        attendees=[{"email": "yo@example.com", "self": True, "responseStatus": "declined"}],
    )

    assert to_meeting(cancelled, BOGOTA) is None
    assert to_meeting(declined, BOGOTA) is None


# --- Errores ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "error_type", "expected"),
    [
        (http_error(401), CalendarNotAuthorizedError, "google-login"),
        (http_error(403), CalendarError, "Calendar API"),
        (http_error(404), CalendarError, "primary"),
        (http_error(500), CalendarError, "500"),
        (RefreshError("revocado"), CalendarNotAuthorizedError, "google-login"),
        (httplib2.HttpLib2Error("caído"), CalendarError, "No pude conectar"),
        (TimeoutError("timeout"), CalendarError, "No pude conectar"),
    ],
)
def test_api_errors_become_calendar_errors(error: Exception, error_type: type, expected: str) -> None:
    calendar = make_calendar(FakeService(error))

    with pytest.raises(error_type, match=expected):
        calendar.list_meetings(date(2026, 10, 29), date(2026, 10, 29))


@pytest.mark.parametrize(
    ("error", "error_type"),
    [
        (GoogleNotAuthorizedError("sin token"), CalendarNotAuthorizedError),
        (GoogleAuthError("sin red"), CalendarError),
    ],
)
def test_auth_errors_from_service_factory_become_calendar_errors(error: Exception, error_type: type) -> None:
    def factory() -> FakeService:
        raise error

    calendar = GoogleCalendar(service_factory=factory, calendar_id="primary", timezone=BOGOTA)

    with pytest.raises(error_type, match=str(error)):
        calendar.list_meetings(date(2026, 10, 29), date(2026, 10, 29))
