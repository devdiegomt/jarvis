import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httplib2
import pytest
from googleapiclient.errors import HttpError

from jarvis.agenda import CalendarNotAuthorizedError, SampleCalendar, supports_writing
from jarvis.agenda.google import GoogleCalendar, google_service_factory, to_meeting
from jarvis.google_auth import CALENDAR_EVENTS_SCOPE, CALENDAR_SCOPE, GoogleNotAuthorizedError, token_scopes
from jarvis.tools import ToolRegistry, build_registry

TZ = ZoneInfo("America/Bogota")
NOW = datetime(2026, 10, 30, 8, 0, tzinfo=TZ)  # viernes


def now() -> datetime:
    return NOW


# --- Calendario de ejemplo --------------------------------------------------


def test_sample_calendar_writes_in_memory() -> None:
    calendar = SampleCalendar(TZ)
    day = date(2026, 10, 30)
    daily = calendar.list_meetings(day, day)[0]

    created = calendar.create_event("Dentista", NOW.replace(hour=15), NOW.replace(hour=16), "Centro", None)
    calendar.move_event(daily.id, NOW.replace(day=31, hour=10), NOW.replace(day=31, hour=10, minute=30))  # type: ignore[arg-type]

    titles_today = [m.title for m in calendar.list_meetings(day, day)]
    assert "Daily del equipo" not in titles_today and "Dentista" in titles_today
    assert [m.title for m in calendar.list_meetings(date(2026, 10, 31), date(2026, 10, 31))][0] == "Daily del equipo"
    calendar.delete_event(created.id)  # type: ignore[arg-type]
    assert "Dentista" not in [m.title for m in calendar.list_meetings(day, day)]
    assert supports_writing(calendar)


# --- Tools -------------------------------------------------------------------


class Asked:
    def __init__(self, answer: bool = True) -> None:
        self.prompts: list[str] = []
        self.answer = answer

    def __call__(self, prompt: str) -> bool:
        self.prompts.append(prompt)
        return self.answer


def registry(calendar: Any, answer: bool = True) -> tuple[ToolRegistry, Asked]:
    asked = Asked(answer)
    return build_registry(calendar, confirm=asked, now=now), asked


def test_write_tools_need_confirmation_and_the_clock() -> None:
    reg, _ = registry(SampleCalendar(TZ))

    for name in ("crear_evento", "mover_evento", "cancelar_evento"):
        assert reg.get(name).requires_confirmation  # type: ignore[union-attr]
    assert "crear_evento" not in build_registry(SampleCalendar(TZ)).names()  # sin reloj no se registran


def test_create_event_shows_details_and_conflicts() -> None:
    calendar = SampleCalendar(TZ)
    reg, asked = registry(calendar)

    result = reg.execute("crear_evento", {"titulo": "Dentista", "inicio": "2026-10-30 09:00", "ubicacion": "Centro"})

    assert asked.prompts == [
        "Voy a agendar en tu calendario:\n«Dentista»\nviernes 30 de octubre, 09:00 a 10:00\nLugar: Centro"
        "\n⚠ Choca con: «Daily del equipo» (09:30-10:00)"
    ]
    created = json.loads(result.content)["creado"]
    assert created["titulo"] == "Dentista" and created["inicio"] == "2026-10-30 09:00"


def test_declined_confirmation_creates_nothing() -> None:
    calendar = SampleCalendar(TZ)
    reg, _ = registry(calendar, answer=False)

    result = reg.execute("crear_evento", {"titulo": "Dentista", "inicio": "2026-10-30 15:00"})

    assert "canceló" in result.content
    assert "Dentista" not in [m.title for m in calendar.list_meetings(date(2026, 10, 30), date(2026, 10, 30))]


@pytest.mark.parametrize(
    ("tool_input", "expected"),
    [
        ({"titulo": "X", "inicio": "2026-10-29 15:00"}, "ya pasó"),
        ({"titulo": "X", "inicio": "mañana"}, "YYYY-MM-DD HH:MM"),
        ({"titulo": "  ", "inicio": "2026-10-30 15:00"}, "título"),
        ({"titulo": "X", "inicio": "2026-10-30 15:00", "duracion_minutos": 2}, "duración"),
        ({"titulo": "X", "inicio": "2030-01-01 15:00"}, "dos años"),
    ],
)
def test_invalid_events_are_rejected_without_asking(tool_input: dict, expected: str) -> None:
    reg, asked = registry(SampleCalendar(TZ))

    result = reg.execute("crear_evento", tool_input)

    assert result.is_error and expected in result.content
    assert asked.prompts == []


def sample_id(calendar: SampleCalendar, title: str) -> str:
    meeting = next(m for m in calendar.list_meetings(date(2026, 10, 30), date(2026, 10, 30)) if m.title == title)
    return str(meeting.id)


def test_move_keeps_the_duration_and_warns_about_conflicts() -> None:
    calendar = SampleCalendar(TZ)
    reg, asked = registry(calendar)
    event_id = sample_id(calendar, "Planificación semanal")

    result = reg.execute("mover_evento", {"id": event_id, "nuevo_inicio": "2026-10-30 09:15"})

    assert asked.prompts[0].startswith(
        "Voy a mover «Planificación semanal»\nde: viernes 30 de octubre, 16:30 a 17:15\n"
        "a: viernes 30 de octubre, 09:15 a 10:00"
    )
    assert "Choca con: «Daily del equipo»" in asked.prompts[0]
    assert json.loads(result.content)["movido"]["fin"] == "2026-10-30 10:00"


def test_invitations_from_others_are_never_touched() -> None:
    calendar = SampleCalendar(TZ)
    reg, asked = registry(calendar)
    event_id = sample_id(calendar, "Revisión de propuesta del cliente")

    moved = reg.execute("mover_evento", {"id": event_id, "nuevo_inicio": "2026-10-30 18:00"})
    cancelled = reg.execute("cancelar_evento", {"id": event_id})

    assert moved.is_error and cancelled.is_error and "otra persona" in cancelled.content
    assert asked.prompts == []


def test_cancel_event() -> None:
    calendar = SampleCalendar(TZ)
    reg, asked = registry(calendar)
    event_id = sample_id(calendar, "Daily del equipo")

    result = reg.execute("cancelar_evento", {"id": event_id})

    assert asked.prompts == ["Voy a cancelar «Daily del equipo»\nviernes 30 de octubre, 09:30 a 10:00"]
    assert json.loads(result.content)["cancelado"]["titulo"] == "Daily del equipo"
    assert reg.execute("cancelar_evento", {"id": event_id}).is_error  # ya no existe


def test_meetings_tool_returns_ids_and_ownership() -> None:
    reg, _ = registry(SampleCalendar(TZ))

    meetings = json.loads(reg.execute("get_reuniones", {"fecha": "2026-10-30"}).content)["reuniones"]

    assert meetings[0]["id"].startswith("ejemplo_") and meetings[0]["organizas_tu"] is True
    assert meetings[1]["organizas_tu"] is False


# --- Google Calendar ---------------------------------------------------------


class Request:
    def __init__(self, result: Any) -> None:
        self.result = result

    def execute(self) -> Any:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Events:
    def __init__(self, results: dict[str, Any]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, method: str) -> Any:
        def call(**kwargs: Any) -> Request:
            self.calls.append((method, kwargs))
            return Request(self.results.get(method, {}))

        return call


def google(results: dict[str, Any]) -> tuple[GoogleCalendar, Events]:
    events = Events(results)
    service = type("S", (), {"events": lambda _self: events})()
    return GoogleCalendar(service_factory=lambda: service, calendar_id="primary", timezone=TZ), events


EVENT = {
    "id": "abc123",
    "summary": "Dentista",
    "start": {"dateTime": "2026-10-30T15:00:00-05:00"},
    "end": {"dateTime": "2026-10-30T16:00:00-05:00"},
    "organizer": {"self": True},
}


def test_google_create_never_notifies_anyone() -> None:
    calendar, events = google({"insert": EVENT})

    meeting = calendar.create_event("Dentista", NOW.replace(hour=15), NOW.replace(hour=16), "Centro", "Traer exámenes")

    method, kwargs = events.calls[0]
    assert method == "insert" and kwargs["sendUpdates"] == "none"
    assert kwargs["body"]["start"] == {"dateTime": "2026-10-30T15:00:00-05:00", "timeZone": "America/Bogota"}
    assert kwargs["body"]["location"] == "Centro" and kwargs["body"]["description"] == "Traer exámenes"
    assert kwargs["body"]["extendedProperties"] == {"private": {"jarvis": "1"}}
    assert meeting.id == "abc123" and meeting.organized_by_me


def test_google_move_and_delete() -> None:
    calendar, events = google({"patch": {**EVENT, "start": {"dateTime": "2026-10-30T17:00:00-05:00"}}, "delete": ""})

    calendar.move_event("abc123", NOW.replace(hour=17), NOW.replace(hour=18))
    calendar.delete_event("abc123")

    assert [(m, k["eventId"], k["sendUpdates"]) for m, k in events.calls] == [
        ("patch", "abc123", "none"),
        ("delete", "abc123", "none"),
    ]


def test_google_missing_event_is_none() -> None:
    calendar, _ = google({"get": HttpError(httplib2.Response({"status": 404}), b"{}")})

    assert calendar.get_event("no-existe") is None


def test_google_write_without_permission_explains_how_to_fix_it() -> None:
    error = HttpError(httplib2.Response({"status": 403}), b'{"error": {"message": "Request had insufficient authentication scopes."}}')
    calendar, _ = google({"insert": error})

    with pytest.raises(CalendarNotAuthorizedError, match="google-login"):
        calendar.create_event("Dentista", NOW.replace(hour=15), NOW.replace(hour=16), None, None)


def test_invitations_and_recurring_instances_are_flagged() -> None:
    invitation = {**EVENT, "organizer": {"email": "laura@example.com"}, "recurringEventId": "serie1"}

    meeting = to_meeting(invitation, TZ)

    assert meeting is not None and not meeting.organized_by_me and meeting.recurring


# --- Permisos -----------------------------------------------------------------


def test_reading_works_with_the_old_read_only_permission(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    built: list[Any] = []
    credentials = type("C", (), {"scopes": [CALENDAR_SCOPE]})()
    monkeypatch.setattr("jarvis.agenda.google.load_credentials", lambda _file, _scopes: credentials)
    monkeypatch.setattr("jarvis.agenda.google.build", lambda *args, **kwargs: built.append(kwargs) or "service")

    assert google_service_factory(tmp_path / "token.json")() == "service"

    credentials.scopes = ["https://www.googleapis.com/auth/gmail.send"]
    with pytest.raises(GoogleNotAuthorizedError):
        google_service_factory(tmp_path / "token.json")()


def test_token_scopes_and_status_line(tmp_path: Path, isolated_config_dir: Path) -> None:
    from jarvis.status import status_report

    token = isolated_config_dir / "token.json"
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(json.dumps({"scopes": [CALENDAR_SCOPE]}))
    env = {"ANTHROPIC_API_KEY": "sk-test", "JARVIS_CALENDAR": "google"}

    assert token_scopes(token) == [CALENDAR_SCOPE]
    assert "solo lectura" in "\n".join(status_report(env, None, {}))

    token.write_text(json.dumps({"scopes": [CALENDAR_EVENTS_SCOPE]}))
    assert "Calendario: Google Calendar\n" in "\n".join(status_report(env, None, {})) + "\n"
    assert token_scopes(tmp_path / "no-existe.json") == []
