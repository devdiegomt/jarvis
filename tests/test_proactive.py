from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from jarvis.agenda import CalendarError, Meeting
from jarvis.agenda.google import to_meeting
from jarvis.chat import ChannelError
from jarvis.config import ConfigError, ProactiveSettings, load_proactive_settings
from jarvis.proactive import NoticeLog, ProactiveNotifier, describe_proactive, evening_preview, meeting_alert
from jarvis.tasks import TaskStore

TZ = ZoneInfo("America/Bogota")
OWNER = "987654321"


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **kwargs: float) -> None:
        self.moment += timedelta(**kwargs)


class Calendar:
    name = "prueba"

    def __init__(self, meetings: list[Meeting], error: Exception | None = None) -> None:
        self.meetings = meetings
        self.error = error
        self.calls: list[tuple[date, date]] = []

    def list_meetings(self, start: date, end: date) -> list[Meeting]:
        self.calls.append((start, end))
        if self.error:
            raise self.error
        return [m for m in self.meetings if start <= (m.start.date() if isinstance(m.start, datetime) else m.start) <= end]


class Channel:
    name = "prueba"

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.fail = False

    def send_text(self, to: str, text: str) -> None:
        assert to == OWNER
        if self.fail:
            raise ChannelError("sin red")
        self.sent.append(text)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)  # 2 de noviembre de 2026: lunes


def meeting(title: str, start: datetime, minutes: int = 60, **extra: object) -> Meeting:
    return Meeting(title=title, start=start, end=start + timedelta(minutes=minutes), id=title.lower(), **extra)  # type: ignore[arg-type]


def notifier(
    tmp_path: Path, clock: Clock, calendar: Calendar, channel: Channel, settings: ProactiveSettings | None = None
) -> ProactiveNotifier:
    db = tmp_path / "jarvis.db"
    return ProactiveNotifier(
        calendar=calendar,
        tasks=TaskStore(db, now=clock),
        channel=channel,
        owner=OWNER,
        settings=settings or ProactiveSettings(meeting_lead_minutes=10, evening_time=None),
        log=NoticeLog(db),
        timezone=TZ,
        now=clock,
    )


# --- Configuración ----------------------------------------------------------


def test_defaults_and_switches() -> None:
    assert load_proactive_settings({}) == ProactiveSettings(10, time(20, 0))
    assert load_proactive_settings({"JARVIS_AVISO_REUNION": "0", "JARVIS_VISTAZO_MANANA": "no"}) == ProactiveSettings(0, None)
    assert load_proactive_settings({"JARVIS_VISTAZO_MANANA": "21:30"}).evening_time == time(21, 30)


@pytest.mark.parametrize(("name", "value"), [("JARVIS_AVISO_REUNION", "diez"), ("JARVIS_AVISO_REUNION", "500"), ("JARVIS_VISTAZO_MANANA", "8pm")])
def test_invalid_settings(name: str, value: str) -> None:
    with pytest.raises(ConfigError, match=name):
        load_proactive_settings({name: value})


def test_describe() -> None:
    assert describe_proactive(ProactiveSettings(10, time(20, 0))) == (
        "10 min antes de cada reunión; vistazo a mañana a las 20:00 (dom–jue)"
    )
    assert describe_proactive(ProactiveSettings(0, None)) == "desactivados"


# --- Antes de cada reunión --------------------------------------------------


def test_alert_is_sent_once_inside_the_window(tmp_path: Path) -> None:
    clock, channel = Clock(at(2, 9, 49)), Channel()
    proactive = notifier(tmp_path, clock, Calendar([meeting("Daily", at(2, 10))]), channel)

    assert proactive.check() == 0  # 11 minutos antes: todavía no
    clock.advance(minutes=1)
    assert proactive.check() == 1
    clock.advance(minutes=1)
    assert proactive.check() == 0  # ya se avisó

    assert channel.sent == ["📅 En 10 minutos: Daily\n10:00–11:00"]


def test_no_late_alerts_after_the_meeting_started(tmp_path: Path) -> None:
    channel = Channel()
    proactive = notifier(tmp_path, Clock(at(2, 10, 5)), Calendar([meeting("Daily", at(2, 10))]), channel)

    assert proactive.check() == 0 and channel.sent == []


def test_alerts_survive_restarts_but_moved_meetings_alert_again(tmp_path: Path) -> None:
    clock, channel = Clock(at(2, 9, 55)), Channel()
    calendar = Calendar([meeting("Daily", at(2, 10))])
    notifier(tmp_path, clock, calendar, channel).check()

    assert notifier(tmp_path, clock, calendar, channel).check() == 0  # reinicio: no repite

    calendar.meetings = [meeting("Daily", at(2, 10, 3))]  # se movió 3 minutos
    assert notifier(tmp_path, clock, calendar, channel).check() == 1


def test_failed_send_is_retried(tmp_path: Path) -> None:
    clock, channel = Clock(at(2, 9, 52)), Channel()
    proactive = notifier(tmp_path, clock, Calendar([meeting("Daily", at(2, 10))]), channel)
    channel.fail = True

    assert proactive.check() == 0
    channel.fail = False
    clock.advance(minutes=1)
    assert proactive.check() == 1
    assert channel.sent[0].startswith("📅 En 7 minutos: Daily")


def test_calendar_is_read_every_five_minutes_not_every_minute(tmp_path: Path) -> None:
    clock, calendar = Clock(at(2, 8, 0)), Calendar([])
    proactive = notifier(tmp_path, clock, calendar, Channel())

    for _ in range(10):
        proactive.check()
        clock.advance(minutes=1)

    assert len(calendar.calls) == 2
    assert calendar.calls[0] == (date(2026, 11, 2), date(2026, 11, 3))


def test_calendar_errors_do_not_stop_the_alerts(tmp_path: Path) -> None:
    calendar = Calendar([], error=CalendarError("sin red"))
    proactive = notifier(tmp_path, Clock(at(2, 9, 55)), calendar, Channel())

    assert proactive.check() == 0  # registra el problema y sigue


def test_all_day_events_get_no_alert(tmp_path: Path) -> None:
    channel = Channel()
    holiday = Meeting(title="Festivo", start=date(2026, 11, 2), end=date(2026, 11, 2), all_day=True, id="f")
    notifier(tmp_path, Clock(at(2, 0, 0)), Calendar([holiday]), channel).check()

    assert channel.sent == []


def test_alert_text_with_people_place_and_link() -> None:
    m = meeting(
        "Revisión",
        at(2, 12),
        attendees=("Laura", "Carlos", "Ana", "Beto"),
        location="Oficina 3",
        link="https://meet.google.com/abc-defg-hij",
    )

    assert meeting_alert(m, at(2, 11, 59)) == (
        "📅 En 1 minuto: Revisión\n12:00–13:00 · con Laura, Carlos, Ana y 1 más\n📍 Oficina 3\n"
        "🔗 https://meet.google.com/abc-defg-hij"
    )
    zoom = meeting("Zoom", at(2, 12), location="https://zoom.us/j/1", link="https://zoom.us/j/1")
    assert "📍" not in meeting_alert(zoom, at(2, 12))  # el enlace no se repite como lugar
    assert meeting_alert(zoom, at(2, 12)).startswith("📅 Ya empieza: Zoom")


# --- Vistazo a mañana -------------------------------------------------------


def evening(tmp_path: Path, clock: Clock, calendar: Calendar, channel: Channel) -> ProactiveNotifier:
    return notifier(tmp_path, clock, calendar, channel, ProactiveSettings(0, time(20, 0)))


def test_evening_preview_once_on_work_nights(tmp_path: Path) -> None:
    clock, channel = Clock(at(2, 19, 59)), Channel()  # lunes
    tomorrow = [meeting("Daily", at(3, 7, 30), 30), meeting("Almuerzo", at(3, 12))]
    proactive = evening(tmp_path, clock, Calendar(tomorrow), channel)
    TaskStore(tmp_path / "jarvis.db", now=clock).add("Renovar el pasaporte", date(2026, 11, 3))

    assert proactive.check() == 0
    clock.advance(minutes=1)
    assert proactive.check() == 1
    clock.advance(hours=1)
    assert proactive.check() == 0

    assert channel.sent == [
        "🌙 Mañana, martes 3 de noviembre: 2 reuniones.\n- 07:30–08:00  Daily\n- 12:00–13:00  Almuerzo\n"
        "Pendientes que vencen (o atrasados): Renovar el pasaporte"
    ]


@pytest.mark.parametrize("day", [6, 7])  # viernes y sábado: mañana no es laboral
def test_no_evening_preview_before_weekend_days(tmp_path: Path, day: int) -> None:
    channel = Channel()
    evening(tmp_path, Clock(at(day, 21)), Calendar([]), channel).check()

    assert channel.sent == []


def test_sunday_night_previews_monday() -> None:
    assert evening_preview(date(2026, 11, 9), [], []) == "🌙 Mañana, lunes 9 de noviembre: no tienes reuniones."


# --- Enlaces de Google Calendar ---------------------------------------------


@pytest.mark.parametrize(
    ("extra", "link"),
    [
        ({"hangoutLink": "https://meet.google.com/x"}, "https://meet.google.com/x"),
        (
            {"conferenceData": {"entryPoints": [{"entryPointType": "phone", "uri": "tel:1"}, {"entryPointType": "video", "uri": "https://zoom.us/j/2"}]}},
            "https://zoom.us/j/2",
        ),
        ({"location": "https://teams.microsoft.com/l/abc"}, "https://teams.microsoft.com/l/abc"),
        ({"location": "Oficina"}, None),
    ],
)
def test_video_links_from_google(extra: dict, link: str | None) -> None:
    event = {"summary": "R", "start": {"dateTime": "2026-11-02T10:00:00-05:00"}, "end": {"dateTime": "2026-11-02T11:00:00-05:00"}, **extra}

    assert to_meeting(event, TZ).link == link  # type: ignore[union-attr]


def test_status_shows_the_notices(isolated_config_dir: Path) -> None:
    from jarvis.status import status_report

    text = "\n".join(status_report({"ANTHROPIC_API_KEY": "sk-test", "JARVIS_AVISO_REUNION": "15"}, None, {}))

    assert "Avisos: 15 min antes de cada reunión; vistazo a mañana a las 20:00 (dom–jue)" in text
