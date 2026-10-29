import json
from datetime import UTC, date, datetime
from pathlib import Path

import anthropic
import pytest

from anthropic_fakes import FakeClient, text_response
from jarvis.agenda import CalendarError, CalendarNotAuthorizedError, Meeting
from jarvis.notify import NotificationError, NotificationNotAuthorizedError
from jarvis.storage import SummaryLog
from jarvis.summary import (
    FALLBACK_NOTE,
    NO_MEETINGS_NOTE,
    build_summary,
    format_spanish_date,
    run_with_retries,
    send_daily_summary,
    write_highlights,
)

DAY = date(2026, 10, 29)  # jueves
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)

DEMO = Meeting(
    title="Demo con cliente",
    start=datetime(2026, 10, 29, 9, 30, tzinfo=UTC),
    end=datetime(2026, 10, 29, 10, 0, tzinfo=UTC),
    location="Meet",
    attendees=("Ana",),
)
DAILY = Meeting(
    title="Daily",
    start=datetime(2026, 10, 29, 11, 0, tzinfo=UTC),
    end=datetime(2026, 10, 29, 11, 15, tzinfo=UTC),
)


class FakeCalendar:
    name = "Calendario falso"

    def __init__(self, meetings: list[Meeting]) -> None:
        self.meetings = meetings

    def list_meetings(self, start: date, end: date) -> list[Meeting]:
        assert start == end == DAY
        return self.meetings


class FakeNotifier:
    name = "falso"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, subject: str, body: str) -> None:
        self.sent.append((subject, body))


def connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]


# --- Formato ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "expected"),
    [(date(2026, 10, 29), "jueves 29 de octubre"), (date(2026, 3, 1), "domingo 1 de marzo")],
)
def test_format_spanish_date(day: date, expected: str) -> None:
    assert format_spanish_date(day) == expected


def test_summary_with_highlights_and_agenda() -> None:
    summary = build_summary(DAY, [DEMO, DAILY], "Tienes la demo temprano.", "Google Calendar")

    assert summary.subject == "Tu día: jueves 29 de octubre (2 reuniones)"
    assert "Tienes la demo temprano." in summary.body
    assert "- 09:30-10:00  Demo con cliente (con Ana) · Meet" in summary.body
    assert "- 11:00-11:15  Daily" in summary.body
    assert "Calendario: Google Calendar" in summary.body
    assert summary.ai_generated
    assert summary.meetings_count == 2


def test_summary_singular_subject() -> None:
    assert build_summary(DAY, [DEMO], "x", "c").subject.endswith("(1 reunión)")


def test_summary_without_highlights_uses_fallback_note() -> None:
    summary = build_summary(DAY, [DEMO], None, "c")

    assert FALLBACK_NOTE in summary.body
    assert "Demo con cliente" in summary.body
    assert not summary.ai_generated


def test_summary_for_empty_day() -> None:
    summary = build_summary(DAY, [], None, "c")

    assert summary.subject == "Tu día: jueves 29 de octubre (sin reuniones)"
    assert NO_MEETINGS_NOTE in summary.body
    assert "Agenda:" not in summary.body


# --- Comentario de Claude ---------------------------------------------------


def test_write_highlights_sends_meetings_to_claude() -> None:
    client = FakeClient([text_response("  Día tranquilo.  ")])

    assert write_highlights(client, "test-model", DAY, [DEMO]) == "Día tranquilo."  # type: ignore[arg-type]

    call = client.messages.calls[0]
    assert call["model"] == "test-model"
    assert "texto plano" in call["system"]
    payload = json.loads(call["messages"][0]["content"])
    assert payload["dia"] == "jueves 29 de octubre"
    assert payload["reuniones"][0]["titulo"] == "Demo con cliente"


@pytest.mark.parametrize(
    "response",
    [connection_error(), text_response("", stop_reason="refusal"), text_response("a medias", stop_reason="max_tokens"), text_response("   ")],
)
def test_write_highlights_returns_none_when_it_cannot_help(response: object) -> None:
    client = FakeClient([response])  # type: ignore[list-item]

    assert write_highlights(client, "m", DAY, [DEMO]) is None  # type: ignore[arg-type]


# --- Envío ------------------------------------------------------------------


def send(log: SummaryLog | None, meetings: list[Meeting], responses: list, force: bool = False):  # type: ignore[no-untyped-def]
    notifier = FakeNotifier()
    client = FakeClient(responses)
    summary = send_daily_summary(
        day=DAY,
        calendar=FakeCalendar(meetings),
        notifier=notifier,
        client=client,  # type: ignore[arg-type]
        model="m",
        log=log,
        now=lambda: NOW,
        force=force,
    )
    return summary, notifier, client


def test_sends_summary_and_records_it(tmp_path: Path) -> None:
    log = SummaryLog(tmp_path / "jarvis.db")

    summary, notifier, _ = send(log, [DEMO], [text_response("Ojo con la demo.")])

    assert summary is not None and summary.ai_generated
    assert len(notifier.sent) == 1
    assert "Ojo con la demo." in notifier.sent[0][1]
    assert log.was_sent(DAY)


def test_does_not_send_twice_the_same_day(tmp_path: Path) -> None:
    log = SummaryLog(tmp_path / "jarvis.db")
    log.record_sent(DAY, NOW)

    summary, notifier, client = send(log, [DEMO], [])

    assert summary is None
    assert notifier.sent == []
    assert client.messages.calls == []


def test_force_sends_again(tmp_path: Path) -> None:
    log = SummaryLog(tmp_path / "jarvis.db")
    log.record_sent(DAY, NOW)

    summary, notifier, _ = send(log, [DEMO], [text_response("ok")], force=True)

    assert summary is not None
    assert len(notifier.sent) == 1


def test_dry_run_without_log_always_sends() -> None:
    summary, notifier, _ = send(None, [DEMO], [text_response("ok")])

    assert summary is not None
    assert len(notifier.sent) == 1


def test_empty_day_does_not_call_claude() -> None:
    summary, notifier, client = send(None, [], [])

    assert summary is not None and not summary.ai_generated
    assert client.messages.calls == []
    assert len(notifier.sent) == 1


def test_claude_failure_still_sends_simple_summary() -> None:
    summary, notifier, _ = send(None, [DEMO], [connection_error()])

    assert summary is not None and not summary.ai_generated
    assert FALLBACK_NOTE in notifier.sent[0][1]


def test_failed_send_is_not_recorded(tmp_path: Path) -> None:
    class BrokenNotifier(FakeNotifier):
        def send(self, subject: str, body: str) -> None:
            raise NotificationError("sin red")

    log = SummaryLog(tmp_path / "jarvis.db")
    with pytest.raises(NotificationError):
        send_daily_summary(
            day=DAY,
            calendar=FakeCalendar([]),
            notifier=BrokenNotifier(),
            client=FakeClient([]),  # type: ignore[arg-type]
            model="m",
            log=log,
            now=lambda: NOW,
        )
    assert not log.was_sent(DAY)


# --- Reintentos -------------------------------------------------------------


def test_retries_temporary_errors_until_success() -> None:
    results: list[object] = [CalendarError("sin red"), NotificationError("sin red"), "ok"]
    waits: list[float] = []
    retries: list[int] = []

    def action() -> str:
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return str(result)

    value = run_with_retries(
        action, attempts=3, wait_seconds=60, on_retry=lambda n, _e: retries.append(n), sleep=waits.append
    )

    assert value == "ok"
    assert retries == [1, 2]
    assert waits == [60, 60]


def test_gives_up_after_last_attempt() -> None:
    calls: list[int] = []

    def action() -> None:
        calls.append(1)
        raise CalendarError("sin red")

    with pytest.raises(CalendarError):
        run_with_retries(action, attempts=3, wait_seconds=0, sleep=lambda _s: None)
    assert len(calls) == 3


@pytest.mark.parametrize("error", [CalendarNotAuthorizedError("x"), NotificationNotAuthorizedError("x")])
def test_authorization_errors_are_not_retried(error: Exception) -> None:
    calls: list[int] = []

    def action() -> None:
        calls.append(1)
        raise error

    with pytest.raises(type(error)):
        run_with_retries(action, attempts=3, wait_seconds=0, sleep=lambda _s: None)
    assert len(calls) == 1
