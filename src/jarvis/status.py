"""Comando `jarvis estado`: configuración, tareas programadas y últimas líneas de los registros."""

import os
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from jarvis.config import (
    SUMMARY_LOG_FILE,
    TELEGRAM_LOG_FILE,
    ConfigError,
    load_settings,
    load_telegram_settings,
    read_env,
)
from jarvis.logs import tail
from jarvis.long_term_memory import MemoryStore
from jarvis.reminders import ReminderStore
from jarvis.scheduler import SUMMARY_TASK, TELEGRAM_TASK, SchedulerError, TaskInfo, describe_result
from jarvis.speech import describe_speech
from jarvis.tasks import TaskStore
from jarvis.voice import describe_voice

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

    # Solo cantidades y fechas: el texto de recordatorios, pendientes y recuerdos no se muestra.
    # `estado` solo lee: si la base de datos aún no existe, no la crea.
    db_path = settings.summary.db_path
    if not db_path.exists():
        return lines + ["Recordatorios pendientes: ninguno", "Pendientes: ninguno", "Memoria: vacía"]

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
    return lines


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
