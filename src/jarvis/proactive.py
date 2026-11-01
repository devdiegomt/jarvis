"""Avisos por iniciativa de JARVIS: antes de cada reunión y un vistazo a mañana por la noche.

Los arma el código, sin IA (instantáneos, gratis y con horas exactas), y los envía el proceso de
Telegram en segundo plano. Un registro en SQLite evita repetir un aviso aunque JARVIS se reinicie.
"""

import logging
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, date, datetime, time as day_time, timedelta, tzinfo
from pathlib import Path

from jarvis.agenda import CalendarError, CalendarSource, Meeting
from jarvis.chat import ChannelError, ChatChannel
from jarvis.config import ProactiveSettings
from jarvis.gmail_reader import Email, GmailReader, MailError, MailNotAuthorizedError, watched_query
from jarvis.mail_watch import WatchList
from jarvis.money import MoneyStore
from jarvis.money_report import receivable_alert
from jarvis.summary import format_spanish_date
from jarvis.tasks import TaskStore
from jarvis.weather import WeatherService, day_line

CHECK_INTERVAL_SECONDS = 60
CALENDAR_REFRESH = timedelta(minutes=5)  # el calendario se consulta cada 5 minutos, no cada minuto
EVENING_DAYS = (6, 0, 1, 2, 3)  # domingo a jueves: el día siguiente es laboral
RETENTION = timedelta(days=30)
MAX_ATTENDEES_SHOWN = 3
MAIL_LOOKBACK = timedelta(hours=24)  # tras mucho tiempo apagado, solo los correos del último día
MAX_SNIPPET_CHARS = 200

logger = logging.getLogger("jarvis.chat")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sent_notices (
    key     TEXT PRIMARY KEY,  -- qué se avisó (por ejemplo, reunion:<id>:<inicio>), sin títulos
    sent_at TEXT NOT NULL
);
"""


class NoticeLog:
    """Avisos ya enviados, para no repetirlos (ni tras un reinicio)."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def was_sent(self, key: str) -> bool:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT 1 FROM sent_notices WHERE key = ?", (key,)).fetchone() is not None

    def record(self, key: str, sent_at: datetime) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO sent_notices (key, sent_at) VALUES (?, ?)",
                (key, sent_at.astimezone(UTC).isoformat(timespec="seconds")),
            )

    def first_seen(self, key: str, now: datetime) -> datetime:
        """Cuándo se anotó `key` por primera vez (y lo anota ahora si es la primera)."""
        with closing(self._connect()) as conn, conn:
            row = conn.execute("SELECT sent_at FROM sent_notices WHERE key = ?", (key,)).fetchone()
            if row is not None:
                return datetime.fromisoformat(row[0])
        self.record(key, now)
        return now

    def purge_old(self, now: datetime) -> int:
        cutoff = (now - RETENTION).astimezone(UTC).isoformat(timespec="seconds")
        with closing(self._connect()) as conn, conn:
            return conn.execute("DELETE FROM sent_notices WHERE sent_at < ?", (cutoff,)).rowcount

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.executescript(_SCHEMA)
        return conn


class ProactiveNotifier:
    def __init__(
        self,
        *,
        calendar: CalendarSource,
        tasks: TaskStore,
        channel: ChatChannel,
        owner: str,
        settings: ProactiveSettings,
        log: NoticeLog,
        timezone: tzinfo,
        now: Callable[[], datetime],
        mail: GmailReader | None = None,
        watched: WatchList | None = None,
        mail_interval: timedelta = timedelta(minutes=2),
        weather: WeatherService | None = None,
        money: MoneyStore | None = None,
        receivable_time: day_time | None = None,
    ) -> None:
        self._calendar = calendar
        self._weather = weather
        self._money = money
        self._receivable_time = receivable_time
        self._mail = mail
        self._watched = watched
        self._mail_interval = mail_interval
        self._mail_checked_at: datetime | None = None
        self._mail_warned = False
        self._tasks = tasks
        self._channel = channel
        self._owner = owner
        self._settings = settings
        self._log = log
        self._tz = timezone
        self._now = now
        self._meetings: list[Meeting] = []
        self._meetings_fetched_at: datetime | None = None
        self._last_purge: datetime | None = None

    @property
    def enabled(self) -> bool:
        mail = self._mail is not None and self._watched is not None
        receivables = self._money is not None and self._receivable_time is not None
        return (
            mail
            or receivables
            or self._settings.meeting_lead_minutes > 0
            or self._settings.evening_time is not None
        )

    def check(self) -> int:
        """Una revisión: envía los avisos que toca. Devuelve cuántos se enviaron."""
        sent = 0
        if self._settings.meeting_lead_minutes > 0:
            sent += self._meeting_alerts()
        if self._settings.evening_time is not None:
            sent += self._evening_preview()
        if self._mail is not None and self._watched is not None:
            sent += self._mail_alerts(self._mail, self._watched)
        if self._money is not None and self._receivable_time is not None:
            sent += self._receivable_alerts(self._money, self._receivable_time)
        self._purge_if_due()
        return sent

    def run_forever(
        self, interval: float = CHECK_INTERVAL_SECONDS, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        while True:
            try:
                self.check()
            except Exception:  # un fallo inesperado no debe detener los avisos de las próximas horas
                logger.exception("Error inesperado al revisar los avisos.")
            sleep(interval)

    # --- Antes de cada reunión ----------------------------------------------

    def _meeting_alerts(self) -> int:
        now = self._now()
        lead = timedelta(minutes=self._settings.meeting_lead_minutes)
        sent = 0
        for meeting in self._upcoming_meetings(now):
            start = meeting.start
            # Solo antes de que empiece: si el PC estaba apagado, un aviso tardío ya no sirve.
            if not isinstance(start, datetime) or not start - lead <= now < start:
                continue
            key = f"reunion:{meeting.id or meeting.title}:{start.isoformat()}"  # si se mueve, avisa de nuevo
            if self._send_once(key, meeting_alert(meeting, now)):
                sent += 1
        return sent

    def _upcoming_meetings(self, now: datetime) -> list[Meeting]:
        fetched = self._meetings_fetched_at
        if fetched is None or now - fetched >= CALENDAR_REFRESH:
            today = now.astimezone(self._tz).date()
            try:
                # Hasta mañana: una reunión a las 00:05 se avisa antes de medianoche.
                meetings = self._calendar.list_meetings(today, today + timedelta(days=1))
                self._meetings = [m for m in meetings if not m.all_day]
                self._meetings_fetched_at = now
            except CalendarError as exc:
                logger.warning("No se pudo revisar el calendario para los avisos: %s", exc)
        return self._meetings

    # --- Vistazo a mañana -----------------------------------------------------

    def _evening_preview(self) -> int:
        now = self._now().astimezone(self._tz)
        evening = self._settings.evening_time
        assert evening is not None
        if now.weekday() not in EVENING_DAYS or now.time() < evening:
            return 0
        key = f"vistazo:{now.date().isoformat()}"
        if self._log.was_sent(key):
            return 0
        tomorrow = now.date() + timedelta(days=1)
        try:
            meetings = self._calendar.list_meetings(tomorrow, tomorrow)
        except CalendarError as exc:
            logger.warning("No se pudo preparar el vistazo a mañana: %s", exc)
            return 0
        forecast = self._weather.day(tomorrow) if self._weather is not None else None
        weather = day_line(forecast) if forecast is not None else None
        text = evening_preview(tomorrow, meetings, [t.text for t in self._tasks.due_by(tomorrow)], weather)
        return 1 if self._send_once(key, text) else 0

    # --- Correos de clientes -------------------------------------------------

    def _mail_alerts(self, mail: GmailReader, watched: WatchList) -> int:
        now = self._now()
        if self._mail_checked_at is not None and now - self._mail_checked_at < self._mail_interval:
            return 0
        self._mail_checked_at = now
        patterns = watched.all()
        if not patterns:
            return 0
        # Al activar los avisos no se avisa de correos viejos: solo de los que lleguen desde entonces.
        started = self._log.first_seen("correo:inicio", now)
        since = max(started, now - MAIL_LOOKBACK)
        try:
            emails = mail.search(watched_query(patterns, after=since - timedelta(minutes=1)), max_results=20)
        except MailNotAuthorizedError as exc:
            if not self._mail_warned:  # una vez, no cada 2 minutos
                logger.warning("Avisos de correo en pausa: %s", exc)
                self._mail_warned = True
            return 0
        except MailError as exc:
            logger.warning("No se pudo revisar el correo: %s", exc)
            return 0
        sent = 0
        for email in sorted(emails, key=lambda e: e.received_at):
            watched_since = watched.watched_since(email.sender_email)
            if watched_since is None or email.received_at < max(since, watched_since):
                continue
            if self._send_once(f"correo:{email.id}", mail_alert(email)):
                sent += 1
        return sent

    # --- Cobros a clientes ---------------------------------------------------

    def _receivable_alerts(self, money: MoneyStore, alert_time: day_time) -> int:
        """El día que vence un cobro y, mientras siga sin pagar, cada 7 días; a la hora configurada."""
        now = self._now().astimezone(self._tz)
        if now.time() < alert_time:
            return 0
        today = now.date()
        sent = 0
        for receivable in money.open_receivables():
            due = receivable.due_date
            if due is None or due > today or (today - due).days % 7 != 0:
                continue
            # Sin el cliente ni el monto en la clave (el registro de avisos no guarda contenido).
            if self._send_once(f"cobro:{receivable.id}:{today.isoformat()}", receivable_alert(receivable, today)):
                sent += 1
        return sent

    # --- Envío ---------------------------------------------------------------

    def _send_once(self, key: str, text: str) -> bool:
        """Envía y anota el aviso. Si el canal falla, no se anota y se reintenta en la próxima revisión."""
        if self._log.was_sent(key):
            return False
        try:
            self._channel.send_text(self._owner, text)
        except ChannelError as exc:
            logger.warning("No se pudo enviar un aviso: %s", exc)
            return False
        self._log.record(key, self._now())
        logger.info("Aviso enviado (%s).", key.split(":")[0])  # solo el tipo, nunca el título
        return True

    def _purge_if_due(self) -> None:
        now = self._now()
        if self._last_purge is None or now - self._last_purge >= timedelta(hours=24):
            self._log.purge_old(now)
            self._last_purge = now


def meeting_alert(meeting: Meeting, now: datetime) -> str:
    start, end = meeting.start, meeting.end
    assert isinstance(start, datetime) and isinstance(end, datetime)
    minutes = max(0, round((start - now).total_seconds() / 60))
    when = f"En {minutes} {'minuto' if minutes == 1 else 'minutos'}" if minutes else "Ya empieza"
    detail = f"{start:%H:%M}–{end:%H:%M}"
    if meeting.attendees:
        names = ", ".join(meeting.attendees[:MAX_ATTENDEES_SHOWN])
        more = len(meeting.attendees) - MAX_ATTENDEES_SHOWN
        detail += f" · con {names}" + (f" y {more} más" if more > 0 else "")
    lines = [f"📅 {when}: {meeting.title}", detail]
    if meeting.location and meeting.location != meeting.link:
        lines.append(f"📍 {meeting.location}")
    if meeting.link:
        lines.append(f"🔗 {meeting.link}")
    return "\n".join(lines)


def mail_alert(email: Email) -> str:
    who = email.sender_email if email.sender_name in ("", email.sender_email) else (
        f"{email.sender_name} ({email.sender_email})"
    )
    snippet = email.snippet
    if len(snippet) > MAX_SNIPPET_CHARS:
        snippet = snippet[:MAX_SNIPPET_CHARS] + "…"
    lines = [f"📧 Correo de {who}", f"«{email.subject}»"]
    if snippet:
        lines.append(snippet)
    return "\n".join(lines)


def evening_preview(
    day: date, meetings: list[Meeting], due_tasks: list[str], weather: str | None = None
) -> str:
    title = f"🌙 Mañana, {format_spanish_date(day)}"
    if meetings:
        count = len(meetings)
        lines = [f"{title}: {count} {'reunión' if count == 1 else 'reuniones'}."]
        for meeting in meetings:
            when = "Todo el día" if meeting.all_day else f"{meeting.start:%H:%M}–{meeting.end:%H:%M}"
            lines.append(f"- {when}  {meeting.title}")
    else:
        lines = [f"{title}: no tienes reuniones."]
    if weather:
        lines.insert(1, weather)
    if due_tasks:
        lines.append("Pendientes que vencen (o atrasados): " + "; ".join(due_tasks))
    return "\n".join(lines)


def describe_proactive(settings: ProactiveSettings) -> str:
    """Para `estado`."""
    parts = []
    if settings.meeting_lead_minutes > 0:
        parts.append(f"{settings.meeting_lead_minutes} min antes de cada reunión")
    if settings.evening_time is not None:
        parts.append(f"vistazo a mañana a las {settings.evening_time:%H:%M} (dom–jue)")
    return "; ".join(parts) if parts else "desactivados"
