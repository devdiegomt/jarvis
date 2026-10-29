"""Programación del resumen diario (Programador de tareas de Windows, o cron)."""

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

TASK_NAME = r"JARVIS\ResumenDiario"
SUMMARY_ARGUMENTS = "-m jarvis resumen --programado"

Runner = Callable[..., subprocess.CompletedProcess[Any]]


class SchedulerError(Exception):
    """No se pudo registrar o quitar la tarea programada."""


@dataclass(frozen=True)
class ScheduledCommand:
    executable: Path
    arguments: str
    working_dir: Path


def summary_command(project_dir: Path, python: Path = Path(sys.executable)) -> ScheduledCommand:
    """Comando que ejecuta el resumen. En Windows usa `pythonw` para no abrir ninguna ventana."""
    pythonw = python.with_name("pythonw.exe")
    executable = pythonw if pythonw.exists() else python
    return ScheduledCommand(executable, SUMMARY_ARGUMENTS, project_dir)


def build_task_xml(command: ScheduledCommand, send_time: time, start_day: date, user_id: str | None) -> str:
    """Definición de la tarea: de lunes a viernes, solo con la sesión iniciada."""
    start = datetime.combine(start_day, send_time).isoformat(timespec="seconds")
    user = f"<UserId>{escape(user_id)}</UserId>" if user_id else ""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>JARVIS: envía por correo el resumen del día.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <DaysOfWeek><Monday /><Tuesday /><Wednesday /><Thursday /><Friday /></DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>
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
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
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


def install_windows_task(
    command: ScheduledCommand, send_time: time, start_day: date, run: Runner = subprocess.run
) -> None:
    xml = build_task_xml(command, send_time, start_day, _windows_user())
    with tempfile.TemporaryDirectory() as tmp:
        xml_file = Path(tmp) / "jarvis-resumen.xml"
        xml_file.write_text(xml, encoding="utf-16")
        _schtasks(["/Create", "/TN", TASK_NAME, "/XML", str(xml_file), "/F"], run)


def remove_windows_task(run: Runner = subprocess.run) -> None:
    _schtasks(["/Delete", "/TN", TASK_NAME, "/F"], run)


def cron_line(command: ScheduledCommand, send_time: time) -> str:
    """Línea de crontab equivalente (lunes a viernes) para Mac o Linux."""
    return (
        f"{send_time.minute} {send_time.hour} * * 1-5 "
        f"cd {shlex.quote(str(command.working_dir))} && "
        f"{shlex.quote(str(command.executable))} {command.arguments}"
    )


def _windows_user() -> str | None:
    user, domain = os.environ.get("USERNAME"), os.environ.get("USERDOMAIN")
    if user and domain:
        return f"{domain}\\{user}"
    return user


def _schtasks(args: list[str], run: Runner) -> None:
    try:
        result = run(["schtasks", *args], capture_output=True, text=True, errors="replace")
    except FileNotFoundError as exc:
        raise SchedulerError("No encontré `schtasks`. Este comando solo funciona en Windows.") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SchedulerError(f"El Programador de tareas devolvió un error: {detail}")
