"""Comandos directos del chat (/hoy, /pendientes, /recordatorios, /clima, /gasto).

Se responden en código, sin IA: son instantáneos y no gastan créditos. Para preguntas abiertas
sigue estando el chat con Claude.
"""

from collections.abc import Callable
from datetime import date, datetime, tzinfo

from jarvis.agenda import CalendarError, CalendarSource, meeting_to_line
from jarvis.dates import format_spanish_date
from jarvis.reminders import ReminderStore
from jarvis.summary import task_to_line
from jarvis.tasks import TaskStore
from jarvis.usage import UsageLog, spending_text
from jarvis.weather import WeatherError, WeatherService, day_line, weather_text

NO_CITY_TEXT = (
    "Para ver el clima, configura tu ciudad en el archivo .env (JARVIS_CIUDAD=Zipaquirá y "
    "JARVIS_PAIS=CO) y reinicia JARVIS."
)
NO_TASKS_TEXT = "No tienes pendientes. Dime, por ejemplo, «anota renovar el pasaporte para el viernes»."
NO_REMINDERS_TEXT = (
    "No tienes recordatorios programados. Dime, por ejemplo, «recuérdame a las 5 llamar a Laura»."
)


def today_text(
    *,
    calendar: CalendarSource,
    tasks: TaskStore,
    reminders: ReminderStore,
    weather: WeatherService | None,
    now: datetime,
    timezone: tzinfo,
) -> str:
    """Agenda, clima, recordatorios y pendientes de hoy."""
    today = now.astimezone(timezone).date()
    lines = [f"📅 Hoy, {format_spanish_date(today)}"]
    forecast = weather.day(today) if weather is not None else None
    if forecast is not None:
        lines.append(day_line(forecast))

    try:
        meetings = calendar.list_meetings(today, today)
        if meetings:
            lines += ["", "Reuniones:"] + [f"- {meeting_to_line(m)}" for m in meetings]
        else:
            lines += ["", "Sin reuniones."]
    except CalendarError as exc:
        lines += ["", f"No pude leer el calendario: {exc}"]

    todays = [r for r in reminders.pending() if r.due_at.astimezone(timezone).date() == today]
    if todays:
        lines += ["", "Recordatorios:"]
        lines += [f"- {r.due_at.astimezone(timezone):%H:%M}  {r.text}" for r in todays]

    due = tasks.due_by(today)
    if due:
        lines += ["", "Pendientes (vencen hoy o atrasados):"] + [f"- {task_to_line(t, today)}" for t in due]
    return "\n".join(lines)


def tasks_text(tasks: TaskStore, today: date) -> str:
    open_tasks = tasks.open()
    if not open_tasks:
        return NO_TASKS_TEXT
    lines = [f"📝 Pendientes ({len(open_tasks)}):"]
    for task in open_tasks:
        if task.due_date is None:
            lines.append(f"- {task.text}")
        elif task.due_date < today:
            lines.append(f"- {task.text} (atrasado: era para el {task.due_date:%d/%m})")
        else:
            lines.append(f"- {task.text} (para {_relative_day(task.due_date, today)})")
    return "\n".join(lines)


def reminders_text(reminders: ReminderStore, now: datetime, timezone: tzinfo) -> str:
    pending = sorted(reminders.pending(), key=lambda r: r.due_at)
    if not pending:
        return NO_REMINDERS_TEXT
    today = now.astimezone(timezone).date()
    lines = [f"⏰ Recordatorios ({len(pending)}):"]
    for reminder in pending:
        local = reminder.due_at.astimezone(timezone)
        lines.append(f"- {_relative_day(local.date(), today)}, {local:%H:%M}: {reminder.text}")
    return "\n".join(lines)


def weather_command_text(weather: WeatherService | None, today: date) -> str:
    if weather is None:
        return NO_CITY_TEXT
    try:
        return weather_text(weather.report(), today)
    except WeatherError as exc:
        return str(exc)


def _relative_day(day: date, today: date) -> str:
    delta = (day - today).days
    if delta == 0:
        return "hoy"
    if delta == 1:
        return "mañana"
    return f"el {format_spanish_date(day)}"


def build_quick_commands(
    *,
    calendar: CalendarSource,
    tasks: TaskStore,
    reminders: ReminderStore,
    weather: WeatherService | None,
    usage: UsageLog,
    now: Callable[[], datetime],
    timezone: tzinfo,
) -> dict[str, Callable[[], str]]:
    """Comando ("/hoy") → función que arma la respuesta."""

    def today() -> date:
        return now().astimezone(timezone).date()

    return {
        "/hoy": lambda: today_text(
            calendar=calendar, tasks=tasks, reminders=reminders, weather=weather, now=now(), timezone=timezone
        ),
        "/pendientes": lambda: tasks_text(tasks, today()),
        "/recordatorios": lambda: reminders_text(reminders, now(), timezone),
        "/clima": lambda: weather_command_text(weather, today()),
        "/gasto": lambda: spending_text(usage, now(), timezone),
    }
