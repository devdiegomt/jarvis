"""Comandos directos del chat (/hoy, /pendientes, /recordatorios, /clima, /gasto).

Se responden en código, sin IA: son instantáneos y no gastan créditos. Para preguntas abiertas
sigue estando el chat con Claude.
"""

from collections.abc import Callable
from datetime import date, datetime, tzinfo
from typing import Any

from jarvis.agenda import CalendarError, CalendarSource, Meeting, meeting_to_line
from jarvis.dates import format_spanish_date
from jarvis.money import MoneyStore, format_money
from jarvis.money_report import due_receivables, month_text, receivable_line, receivables_text, trm_text
from jarvis.reminders import ReminderStore
from jarvis.summary import task_to_line
from jarvis.tasks import TaskStore
from jarvis.trm import TrmService
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
    money: MoneyStore | None = None,
) -> str:
    """Agenda, clima, recordatorios, pendientes y cobros que vencen hoy."""
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

    receivables = due_receivables(money, today) if money is not None else []
    if receivables:
        lines += ["", "Cobros (vencen hoy o vencidos):"] + [f"- {receivable_line(r, today)}" for r in receivables]
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
    money: MoneyStore | None = None,
    trm: TrmService | None = None,
    currency: str = "COP",
) -> dict[str, Callable[[], str]]:
    """Comando ("/hoy") → función que arma la respuesta."""

    def today() -> date:
        return now().astimezone(timezone).date()

    commands = {
        "/hoy": lambda: today_text(
            calendar=calendar,
            tasks=tasks,
            reminders=reminders,
            weather=weather,
            now=now(),
            timezone=timezone,
            money=money,
        ),
        "/pendientes": lambda: tasks_text(tasks, today()),
        "/recordatorios": lambda: reminders_text(reminders, now(), timezone),
        "/clima": lambda: weather_command_text(weather, today()),
        "/gasto": lambda: spending_text(usage, now(), timezone),
    }
    if money is not None:
        commands["/dinero"] = lambda: month_text(money, today(), currency)
        commands["/cobros"] = lambda: receivables_text(money, today())
    if trm is not None:
        commands["/trm"] = lambda: trm_text(trm, today())
    return commands


def today_data(
    *,
    calendar: CalendarSource,
    tasks: TaskStore,
    reminders: ReminderStore,
    weather: WeatherService | None,
    now: datetime,
    timezone: tzinfo,
    money: MoneyStore | None = None,
) -> dict[str, Any]:
    """Lo mismo que `/hoy`, en datos, para la app y el widget del iPhone (sin IA)."""
    local_now = now.astimezone(timezone)
    today = local_now.date()
    forecast = weather.day(today) if weather is not None else None
    data: dict[str, Any] = {
        "fecha": today.isoformat(),
        "dia": format_spanish_date(today),
        "clima": None,
        "reuniones": [],
        "proxima": None,
        "recordatorios": [],
        "pendientes": [],
        "error_calendario": None,
    }
    if forecast is not None:
        data["clima"] = {
            "linea": day_line(forecast),
            "emoji": forecast.emoji,
            "descripcion": forecast.description,
            "min_c": round(forecast.temp_min),
            "max_c": round(forecast.temp_max),
            "prob_lluvia_pct": forecast.rain_chance,
        }
    try:
        meetings = calendar.list_meetings(today, today)
    except CalendarError as exc:
        data["error_calendario"] = str(exc)
        meetings = []
    for meeting in meetings:
        item = _meeting_to_data(meeting)
        data["reuniones"].append(item)
        ends = meeting.end if isinstance(meeting.end, datetime) else None
        if data["proxima"] is None and not meeting.all_day and ends is not None and ends > local_now:
            data["proxima"] = item
    data["recordatorios"] = [
        {"hora": f"{r.due_at.astimezone(timezone):%H:%M}", "texto": r.text}
        for r in reminders.pending()
        if r.due_at.astimezone(timezone).date() == today
    ]
    data["pendientes"] = [
        {
            "texto": t.text,
            "fecha": t.due_date.isoformat() if t.due_date else None,
            "atrasado": bool(t.due_date and t.due_date < today),
        }
        for t in tasks.due_by(today)
    ]
    data["pendientes_abiertos"] = len(tasks.open())
    data["cobros"] = [
        {
            "cliente": r.client,
            "monto": format_money(r.amount, r.currency),
            "vence": r.due_date.isoformat() if r.due_date else None,
            "dias_de_atraso": r.overdue_days(today),
        }
        for r in (due_receivables(money, today) if money is not None else [])
    ]
    return data


def _meeting_to_data(meeting: Meeting) -> dict[str, Any]:
    timed = isinstance(meeting.start, datetime) and isinstance(meeting.end, datetime)
    return {
        "titulo": meeting.title,
        "inicio": f"{meeting.start:%H:%M}" if timed else None,
        "fin": f"{meeting.end:%H:%M}" if timed else None,
        "todo_el_dia": meeting.all_day,
        "lugar": meeting.location,
        "enlace": meeting.link,
    }
