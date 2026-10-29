"""Tareas programadas de JARVIS en el Programador de tareas de Windows (o líneas de cron).

- Resumen diario: de lunes a viernes a una hora fija.
- Telegram: al iniciar sesión, en segundo plano y sin límite de duración.
"""

import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

PROJECT_DIR = Path(__file__).resolve().parents[2]  # carpeta del proyecto (donde está el .env)
TASK_FOLDER = "JARVIS"
SUMMARY_TASK = rf"{TASK_FOLDER}\ResumenDiario"
TELEGRAM_TASK = rf"{TASK_FOLDER}\Telegram"
SUMMARY_ARGUMENTS = "-m jarvis resumen --programado"
TELEGRAM_ARGUMENTS = "-m jarvis telegram --programado"

Runner = Callable[..., subprocess.CompletedProcess[Any]]


class SchedulerError(Exception):
    """No se pudo registrar, consultar o quitar una tarea programada."""


@dataclass(frozen=True)
class ScheduledCommand:
    executable: Path
    arguments: str
    working_dir: Path


def jarvis_command(
    project_dir: Path, arguments: str, python: Path = Path(sys.executable)
) -> ScheduledCommand:
    """Comando que ejecuta JARVIS. En Windows usa `pythonw` para no abrir ninguna ventana."""
    pythonw = python.with_name("pythonw.exe")
    executable = pythonw if pythonw.exists() else python
    return ScheduledCommand(executable, arguments, project_dir)


def summary_task_xml(command: ScheduledCommand, send_time: time, start_day: date, user_id: str | None) -> str:
    """Resumen: de lunes a viernes; si el PC estaba apagado, se ejecuta al encenderlo."""
    start = datetime.combine(start_day, send_time).isoformat(timespec="seconds")
    trigger = f"""<CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <DaysOfWeek><Monday /><Tuesday /><Wednesday /><Thursday /><Friday /></DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>"""
    return _task_xml(
        command,
        description="JARVIS: envía el resumen del día.",
        trigger=trigger,
        user_id=user_id,
        extra_settings="<StartWhenAvailable>true</StartWhenAvailable>\n    "
        "<ExecutionTimeLimit>PT1H</ExecutionTimeLimit>",
    )


def telegram_task_xml(command: ScheduledCommand, user_id: str | None) -> str:
    """Telegram: al iniciar sesión (con 30 s de margen para que haya red), sin límite de duración.

    Si el proceso termina con error, Windows lo reinicia hasta 3 veces, cada 5 minutos.
    """
    user = f"\n      <UserId>{escape(user_id)}</UserId>" if user_id else ""
    trigger = f"""<LogonTrigger>
      <Enabled>true</Enabled>{user}
      <Delay>PT30S</Delay>
    </LogonTrigger>"""
    return _task_xml(
        command,
        description="JARVIS: chat por Telegram en segundo plano.",
        trigger=trigger,
        user_id=user_id,
        extra_settings="<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n    "
        "<RestartOnFailure>\n      <Interval>PT5M</Interval>\n      <Count>3</Count>\n    </RestartOnFailure>",
    )


def _task_xml(
    command: ScheduledCommand, description: str, trigger: str, user_id: str | None, extra_settings: str
) -> str:
    """Tarea que corre solo con la sesión del usuario iniciada (no guarda su contraseña)."""
    user = f"<UserId>{escape(user_id)}</UserId>" if user_id else ""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{escape(description)}</Description>
  </RegistrationInfo>
  <Triggers>
    {trigger}
  </Triggers>
  <Principals>
    <Principal id="Author">
      {user}
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    {extra_settings}
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(command.executable))}</Command>
      <Arguments>{escape(command.arguments)}</Arguments>
      <WorkingDirectory>{escape(str(command.working_dir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def install_task(name: str, xml: str, run: Runner = subprocess.run) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        xml_file = Path(tmp) / "jarvis-tarea.xml"
        xml_file.write_text(xml, encoding="utf-16")
        _run(["schtasks", "/Create", "/TN", name, "/XML", str(xml_file), "/F"], run)


def start_task(name: str, run: Runner = subprocess.run) -> None:
    _run(["schtasks", "/Run", "/TN", name], run)


def stop_task(name: str, run: Runner = subprocess.run) -> None:
    _run(["schtasks", "/End", "/TN", name], run)


def remove_task(name: str, run: Runner = subprocess.run) -> None:
    _run(["schtasks", "/Delete", "/TN", name, "/F"], run)


def task_state(name: str, run: Runner = subprocess.run) -> str | None:
    """Estado de la tarea (`Ready`, `Running`, `Disabled`…) o None si no existe.

    Se consulta con PowerShell porque devuelve el estado en inglés, sea cual sea el idioma
    de Windows (la salida de `schtasks /Query` está traducida).
    """
    folder, _, task = name.rpartition("\\")
    script = (
        f"(Get-ScheduledTask -TaskPath '\\{folder}\\' -TaskName '{task}' "
        "-ErrorAction SilentlyContinue).State"
    )
    try:
        result = run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise SchedulerError("No encontré PowerShell. Este comando solo funciona en Windows.") from exc
    state = (result.stdout or "").strip()
    return state or None


def cron_line(command: ScheduledCommand, send_time: time) -> str:
    """Línea de crontab equivalente al resumen (lunes a viernes) para Mac o Linux."""
    return f"{send_time.minute} {send_time.hour} * * 1-5 {_cron_command(command)}"


def cron_reboot_line(command: ScheduledCommand) -> str:
    """Línea de crontab que arranca un comando al encender el equipo (Mac o Linux)."""
    return f"@reboot {_cron_command(command)}"


def _cron_command(command: ScheduledCommand) -> str:
    return (
        f"cd {shlex.quote(str(command.working_dir))} && "
        f"{shlex.quote(str(command.executable))} {command.arguments}"
    )


def windows_user() -> str | None:
    user, domain = os.environ.get("USERNAME"), os.environ.get("USERDOMAIN")
    if user and domain:
        return f"{domain}\\{user}"
    return user


def _run(args: list[str], run: Runner) -> None:
    try:
        result = run(args, capture_output=True, text=True, errors="replace")
    except FileNotFoundError as exc:
        raise SchedulerError("No encontré `schtasks`. Este comando solo funciona en Windows.") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SchedulerError(f"El Programador de tareas devolvió un error: {detail}")
