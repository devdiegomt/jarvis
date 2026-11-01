"""Comando `jarvis estado`: configuración, tareas programadas y últimas líneas de los registros."""

import os
from collections.abc import Callable, Mapping
from datetime import date, datetime
from pathlib import Path

from jarvis.config import (
    SUMMARY_LOG_FILE,
    TELEGRAM_LOG_FILE,
    ConfigError,
    Settings,
    load_settings,
    load_telegram_settings,
    read_env,
)
from jarvis.logs import tail
from jarvis.long_term_memory import MemoryStore
from jarvis.reminders import ReminderStore
from jarvis.scheduler import SUMMARY_TASK, TELEGRAM_TASK, SchedulerError, TaskInfo, describe_result
from jarvis.proactive import describe_proactive
from jarvis.speech import describe_speech
from jarvis.api.app import describe_api
from jarvis.money import MoneyStore
from jarvis.tasks import TaskStore
from jarvis.usage import UsageLog, spending_text
from jarvis.voice import describe_voice
from jarvis.wake_word import describe_wake_word

LOG_LINES = 5

# Estados que devuelve el Programador de tareas (en inglés, sea cual sea el idioma de Windows).
_STATES = {
    None: "no programada",
    "Ready": "programada (en espera)",
    "Running": "programada y en ejecución",
    "Queued": "programada (a punto de iniciar)",
    "Disabled": "desactivada en el Programador de tareas",
}

TaskInfoReader = Callable[[str], TaskInfo | None]


def status_report(
    env: Mapping[str, str],
    read_task_info: TaskInfoReader | None,
    logs: Mapping[str, Path],
    log_lines: int = LOG_LINES,
) -> list[str]:
    """Líneas del informe. `read_task_info=None` significa que no es Windows."""
    lines = ["Estado de JARVIS", ""]
    lines += _config_lines(env)
    lines.append("")
    lines += _task_lines(read_task_info)
    for label, log_file in logs.items():
        lines += ["", f"Últimas líneas de {label} ({log_file}):"]
        lines += [f"  {line}" for line in tail(log_file, log_lines)] or ["  (sin registros todavía)"]
    return lines


def run_status() -> None:
    from jarvis.scheduler import task_info

    report = status_report(
        read_env(),
        read_task_info=task_info if os.name == "nt" else None,
        logs={"Telegram": TELEGRAM_LOG_FILE, "Resumen": SUMMARY_LOG_FILE},
    )
    print("\n".join(report))


def _config_lines(env: Mapping[str, str]) -> list[str]:
    lines: list[str] = []
    try:
        settings = load_settings(env)
    except ConfigError as exc:
        return [f"Configuración: ⚠ {exc}"]

    source = "Google Calendar" if settings.calendar_source == "google" else "ejemplo (datos simulados)"
    if settings.calendar_source == "google":
        from jarvis.google_auth import CALENDAR_EVENTS_SCOPE, token_scopes

        can_write = CALENDAR_EVENTS_SCOPE in token_scopes(settings.google.token_file)
        source += "" if can_write else " (solo lectura: ejecuta `google-login` para poder agendar)"
    lines.append(f"Calendario: {source}")
    summary = settings.summary
    if summary.enabled:
        channel = "Telegram" if summary.channel == "telegram" else f"Gmail ({summary.recipient})"
        lines.append(f"Resumen diario: {channel}, de lunes a viernes a las {summary.send_time:%H:%M}")
    else:
        lines.append("Resumen diario: no configurado")

    try:
        load_telegram_settings(env)
        lines.append("Telegram: bot configurado y cuenta vinculada")
    except ConfigError as exc:
        lines.append(f"Telegram: ⚠ {exc}")
    lines.append(f"Notas de voz: {describe_voice(settings.voice)}")
    lines.append(f"Respuestas con voz: {describe_speech(settings.speech)}")
    lines.append(f"Hey JARVIS en el PC: {describe_wake_word(settings)}")
    lines.append(f"Búsqueda en internet: {_describe_web(settings)}")
    lines.append(f"Avisos: {describe_proactive(settings.proactive)}")
    lines.append(f"Correo: {_describe_mail(settings)}")
    lines.append(f"App del iPhone: {describe_api(settings.api)}")
    place = ", ".join(part for part in (settings.web.city, settings.web.country) if part)
    lines.append(f"Clima: Open-Meteo para {place}" if place else "Clima: sin ciudad (configura JARVIS_CIUDAD)")

    # Solo cantidades y fechas: el texto de recordatorios, pendientes y recuerdos no se muestra.
    # `estado` solo lee: si la base de datos aún no existe, no la crea.
    db_path = settings.summary.db_path
    if not db_path.exists():
        return lines + [
            "Recordatorios pendientes: ninguno",
            "Pendientes: ninguno",
            "Memoria: vacía",
            "Dinero: sin movimientos ni cobros",
            "Gasto en Claude: nada todavía",
        ]

    def now() -> datetime:
        return datetime.now(settings.timezone)

    pending = ReminderStore(db_path, now=now).pending()
    if pending:
        next_at = pending[0].due_at.astimezone(settings.timezone)
        lines.append(f"Recordatorios pendientes: {len(pending)} (el próximo: {next_at:%Y-%m-%d %H:%M})")
    else:
        lines.append("Recordatorios pendientes: ninguno")

    tasks = TaskStore(db_path, now=now)
    open_tasks, due = tasks.open(), tasks.due_by(now().date())
    if open_tasks:
        lines.append(f"Pendientes: {len(open_tasks)} abiertos ({len(due)} para hoy o atrasados)")
    else:
        lines.append("Pendientes: ninguno")
    memories = MemoryStore(db_path, now=now).count()
    if memories:
        lines.append(f"Memoria: {memories} {'dato guardado' if memories == 1 else 'datos guardados'}")
    else:
        lines.append("Memoria: vacía")
    lines.append(f"Dinero: {_describe_money(MoneyStore(db_path, now=now), now().date(), settings)}")
    lines += spending_text(UsageLog(db_path, now=now), now(), settings.timezone).splitlines()
    return lines


def _describe_mail(settings: Settings) -> str:
    if not settings.mail.enabled:
        return "desactivado (JARVIS_CORREO=no)"
    from jarvis.google_auth import GMAIL_READ_SCOPE, token_scopes

    if GMAIL_READ_SCOPE not in token_scopes(settings.google.token_file):
        return "⚠ falta el permiso para leer tu correo: ejecuta `google-login`"
    count = 0
    if settings.summary.db_path.exists():  # `estado` solo lee: no crea la base de datos
        from jarvis.mail_watch import WatchList

        count = len(WatchList(settings.summary.db_path).all())
    if count:
        who = f"{count} {'contacto vigilado' if count == 1 else 'contactos vigilados'}"
    else:
        who = "sin contactos vigilados"
    return f"activo ({who}, revisa cada {settings.mail.check_minutes} min)"


def _describe_money(store: MoneyStore, today: date, settings: Settings) -> str:
    """Solo cantidades: ni montos ni clientes."""
    moves = len(store.moves_between(today.replace(day=1), today))
    receivables = store.open_receivables()
    late = sum(1 for r in receivables if r.overdue_days(today))
    alert = settings.money.receivable_alert_time
    parts = [
        f"{moves} movimiento(s) este mes",
        f"{len(receivables)} cobro(s) pendiente(s)" + (f" ({late} vencido(s))" if late else ""),
        f"aviso de cobros a las {alert:%H:%M}" if alert else "aviso de cobros apagado",
    ]
    return ", ".join(parts)


def _describe_web(settings: Settings) -> str:
    if not settings.web.enabled:
        return "desactivada (JARVIS_BUSQUEDA=no)"
    place = ", ".join(part for part in (settings.web.city, settings.web.country) if part)
    where = f", ubicación: {place}" if place else ", sin ubicación (JARVIS_CIUDAD)"
    return f"activada (hasta {settings.web.max_searches} búsquedas por mensaje{where})"


def _task_lines(read_task_info: TaskInfoReader | None) -> list[str]:
    if read_task_info is None:
        return ["Tareas programadas: solo disponibles en Windows (en Mac o Linux se usa cron)."]
    lines = ["Tareas programadas:"]
    for name, label in ((SUMMARY_TASK, "Resumen diario"), (TELEGRAM_TASK, "Telegram en segundo plano")):
        try:
            info = read_task_info(name)
        except SchedulerError as exc:
            lines.append(f"  {label}: no se pudo consultar ({exc})")
            continue
        state = info.state if info else None
        lines.append(f"  {label}: {_STATES.get(state, state)}")
        if info is not None and info.last_run is not None and info.last_result is not None:
            lines.append(f"    Última ejecución: {info.last_run} ({describe_result(info.last_result)})")
        if name == TELEGRAM_TASK and state == "Ready":
            lines.append(
                "    No está corriendo ahora: arranca al iniciar sesión, o ya mismo con "
                "`uv run jarvis programar-telegram`.\n"
                "    Revisa el registro de abajo por si se detuvo por un error."
            )
    return lines
