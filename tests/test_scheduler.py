import subprocess
import xml.etree.ElementTree as ET
from datetime import date, time
from pathlib import Path
from typing import Any

import pytest

from jarvis.scheduler import (
    TASK_NAME,
    ScheduledCommand,
    SchedulerError,
    build_task_xml,
    cron_line,
    install_windows_task,
    remove_windows_task,
    summary_command,
)

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
COMMAND = ScheduledCommand(
    executable=Path(r"C:\projects\jarvis\.venv\Scripts\pythonw.exe"),
    arguments="-m jarvis resumen --programado",
    working_dir=Path(r"C:\projects\jarvis"),
)


class FakeRun:
    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[list[str]] = []
        self.xml: str | None = None

    def __call__(self, args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if "/XML" in args:
            self.xml = Path(args[args.index("/XML") + 1]).read_text(encoding="utf-16")
        return subprocess.CompletedProcess(args, self.returncode, stdout="", stderr=self.stderr)


def parse(xml: str) -> ET.Element:
    return ET.fromstring(xml.split("?>", 1)[1])


def test_task_xml_runs_weekdays_at_configured_time() -> None:
    root = parse(build_task_xml(COMMAND, time(7, 0), date(2026, 10, 30), user_id=r"PC\devdi"))

    assert root.find("t:Triggers/t:CalendarTrigger/t:StartBoundary", NS).text == "2026-10-30T07:00:00"  # type: ignore[union-attr]
    days = root.find("t:Triggers/t:CalendarTrigger/t:ScheduleByWeek/t:DaysOfWeek", NS)
    assert [day.tag.split("}")[1] for day in days] == ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]  # type: ignore[union-attr]
    assert root.find("t:Settings/t:StartWhenAvailable", NS).text == "true"  # type: ignore[union-attr]
    assert root.find("t:Principals/t:Principal/t:LogonType", NS).text == "InteractiveToken"  # type: ignore[union-attr]
    assert root.find("t:Principals/t:Principal/t:UserId", NS).text == r"PC\devdi"  # type: ignore[union-attr]

    exec_node = root.find("t:Actions/t:Exec", NS)
    assert exec_node.find("t:Command", NS).text == str(COMMAND.executable)  # type: ignore[union-attr]
    assert exec_node.find("t:Arguments", NS).text == "-m jarvis resumen --programado"  # type: ignore[union-attr]
    assert exec_node.find("t:WorkingDirectory", NS).text == str(COMMAND.working_dir)  # type: ignore[union-attr]


def test_task_xml_escapes_special_characters() -> None:
    command = ScheduledCommand(Path("C:/A & B/pythonw.exe"), "-m jarvis", Path("C:/A & B"))

    root = parse(build_task_xml(command, time(7, 0), date(2026, 10, 30), user_id=None))

    assert root.find("t:Actions/t:Exec/t:Command", NS).text == "C:/A & B/pythonw.exe"  # type: ignore[union-attr]
    assert root.find("t:Principals/t:Principal/t:UserId", NS) is None


def test_install_registers_task_with_schtasks() -> None:
    run = FakeRun()

    install_windows_task(COMMAND, time(7, 30), date(2026, 10, 30), run=run)

    args = run.calls[0]
    assert args[:4] == ["schtasks", "/Create", "/TN", TASK_NAME]
    assert args[-1] == "/F"
    assert run.xml is not None and "2026-10-30T07:30:00" in run.xml


def test_remove_deletes_task() -> None:
    run = FakeRun()

    remove_windows_task(run=run)

    assert run.calls == [["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]]


def test_schtasks_failure_raises_scheduler_error() -> None:
    with pytest.raises(SchedulerError, match="Acceso denegado"):
        remove_windows_task(run=FakeRun(returncode=1, stderr="ERROR: Acceso denegado."))


def test_missing_schtasks_raises_scheduler_error() -> None:
    def run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    with pytest.raises(SchedulerError, match="Windows"):
        remove_windows_task(run=run)


def test_summary_command_prefers_pythonw(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.touch()
    (tmp_path / "pythonw.exe").touch()

    command = summary_command(Path("/proyecto"), python=python)

    assert command.executable == tmp_path / "pythonw.exe"
    assert command.arguments == "-m jarvis resumen --programado"


def test_summary_command_falls_back_to_python(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.touch()

    assert summary_command(Path("/proyecto"), python=python).executable == python


def test_cron_line_for_weekdays() -> None:
    command = ScheduledCommand(Path("/home/yo/jarvis/.venv/bin/python"), "-m jarvis resumen --programado", Path("/home/yo/mi jarvis"))

    assert cron_line(command, time(7, 5)) == (
        "5 7 * * 1-5 cd '/home/yo/mi jarvis' && /home/yo/jarvis/.venv/bin/python -m jarvis resumen --programado"
    )
