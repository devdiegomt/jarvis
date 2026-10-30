import subprocess
import xml.etree.ElementTree as ET
from datetime import date, time
from pathlib import Path
from typing import Any

import pytest

from jarvis import scheduler
from jarvis.scheduler import (
    SUMMARY_ARGUMENTS,
    SUMMARY_TASK,
    TELEGRAM_ARGUMENTS,
    TELEGRAM_TASK,
    ScheduledCommand,
    SchedulerError,
    cron_line,
    cron_reboot_line,
    install_task,
    jarvis_command,
    remove_task,
    start_task,
    stop_task,
    summary_task_xml,
    TaskInfo,
    describe_result,
    task_info,
    telegram_task_xml,
)

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
SUMMARY = ScheduledCommand(
    executable=Path(r"C:\projects\jarvis\.venv\Scripts\pythonw.exe"),
    arguments=SUMMARY_ARGUMENTS,
    working_dir=Path(r"C:\projects\jarvis"),
)
TELEGRAM = ScheduledCommand(SUMMARY.executable, TELEGRAM_ARGUMENTS, SUMMARY.working_dir)


class FakeRun:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[list[str]] = []
        self.xml: str | None = None

    def __call__(self, args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if "/XML" in args:
            self.xml = Path(args[args.index("/XML") + 1]).read_text(encoding="utf-16")
        return subprocess.CompletedProcess(args, self.returncode, stdout=self.stdout, stderr=self.stderr)


def parse(xml: str) -> ET.Element:
    return ET.fromstring(xml.split("?>", 1)[1])


def text(root: ET.Element, path: str) -> str | None:
    node = root.find(path, NS)
    return None if node is None else node.text


# --- Resumen diario ---------------------------------------------------------


def test_summary_task_runs_weekdays_at_configured_time() -> None:
    root = parse(summary_task_xml(SUMMARY, time(7, 0), date(2026, 10, 30), user_id=r"PC\devdi"))

    assert text(root, "t:Triggers/t:CalendarTrigger/t:StartBoundary") == "2026-10-30T07:00:00"
    days = root.find("t:Triggers/t:CalendarTrigger/t:ScheduleByWeek/t:DaysOfWeek", NS)
    assert days is not None
    assert [day.tag.split("}")[1] for day in days] == ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    assert text(root, "t:Settings/t:StartWhenAvailable") == "true"
    assert text(root, "t:Settings/t:ExecutionTimeLimit") == "PT1H"
    assert text(root, "t:Principals/t:Principal/t:LogonType") == "InteractiveToken"
    assert text(root, "t:Principals/t:Principal/t:UserId") == r"PC\devdi"
    assert text(root, "t:Actions/t:Exec/t:Command") == str(SUMMARY.executable)
    assert text(root, "t:Actions/t:Exec/t:Arguments") == "-m jarvis resumen --programado"
    assert text(root, "t:Actions/t:Exec/t:WorkingDirectory") == str(SUMMARY.working_dir)


def test_task_xml_escapes_special_characters() -> None:
    command = ScheduledCommand(Path("C:/A & B/pythonw.exe"), "-m jarvis", Path("C:/A & B"))

    root = parse(summary_task_xml(command, time(7, 0), date(2026, 10, 30), user_id=None))

    assert text(root, "t:Actions/t:Exec/t:Command") == "C:/A & B/pythonw.exe"
    assert root.find("t:Principals/t:Principal/t:UserId", NS) is None


# --- Telegram en segundo plano ----------------------------------------------


def test_telegram_task_starts_at_logon_without_time_limit() -> None:
    root = parse(telegram_task_xml(TELEGRAM, user_id=r"PC\devdi"))

    assert text(root, "t:Triggers/t:LogonTrigger/t:UserId") == r"PC\devdi"  # solo tu sesión
    assert text(root, "t:Triggers/t:LogonTrigger/t:Delay") == "PT30S"
    assert text(root, "t:Settings/t:ExecutionTimeLimit") == "PT0S"
    assert text(root, "t:Settings/t:MultipleInstancesPolicy") == "IgnoreNew"  # nunca dos copias
    assert text(root, "t:Settings/t:DisallowStartIfOnBatteries") == "false"
    assert text(root, "t:Settings/t:RestartOnFailure/t:Count") == "3"
    assert root.find("t:Settings/t:StartWhenAvailable", NS) is None
    assert text(root, "t:Actions/t:Exec/t:Arguments") == "-m jarvis telegram --programado"


# --- Comandos de schtasks y PowerShell --------------------------------------


def test_install_registers_task_with_schtasks() -> None:
    run = FakeRun()

    install_task(TELEGRAM_TASK, telegram_task_xml(TELEGRAM, None), run=run)

    assert run.calls[0][:4] == ["schtasks", "/Create", "/TN", TELEGRAM_TASK]
    assert run.calls[0][-1] == "/F"
    assert run.xml is not None and "LogonTrigger" in run.xml


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        (start_task, ["schtasks", "/Run", "/TN", TELEGRAM_TASK]),
        (stop_task, ["schtasks", "/End", "/TN", TELEGRAM_TASK]),
        (remove_task, ["schtasks", "/Delete", "/TN", TELEGRAM_TASK, "/F"]),
    ],
)
def test_task_actions(action: Any, expected: list[str]) -> None:
    run = FakeRun()

    action(TELEGRAM_TASK, run=run)

    assert run.calls == [expected]


def test_schtasks_failure_raises_scheduler_error() -> None:
    with pytest.raises(SchedulerError, match="Acceso denegado"):
        remove_task(SUMMARY_TASK, run=FakeRun(returncode=1, stderr="ERROR: Acceso denegado."))


def test_missing_schtasks_raises_scheduler_error() -> None:
    def run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    with pytest.raises(SchedulerError, match="Windows"):
        remove_task(SUMMARY_TASK, run=run)


@pytest.fixture
def powershell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler.shutil, "which", lambda name: f"C:/ps/{name}.exe" if name == "powershell" else None)


def test_task_info_queries_powershell_in_the_jarvis_folder(powershell: None) -> None:
    run = FakeRun(stdout="Ready|1|2026-10-29 18:35\r\n")

    info = task_info(TELEGRAM_TASK, run=run)

    assert info == TaskInfo(state="Ready", last_result=1, last_run="2026-10-29 18:35")
    assert run.calls[0][0] == "C:/ps/powershell.exe"
    script = run.calls[0][-1]
    assert "-TaskPath '\\JARVIS\\'" in script and "-TaskName 'Telegram'" in script
    assert '"' not in script  # sin comillas dobles: se escapan mal al pasar por la línea de comandos


def test_task_info_of_missing_task_is_none(powershell: None) -> None:
    assert task_info(TELEGRAM_TASK, run=FakeRun(stdout="")) is None


def test_task_info_of_task_that_never_ran(powershell: None) -> None:
    info = task_info(TELEGRAM_TASK, run=FakeRun(stdout="Ready|267011|1899-12-30 00:00"))

    assert info is not None and info.last_run is None


def test_powershell_is_found_outside_the_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    builtin = tmp_path / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    builtin.parent.mkdir(parents=True)
    builtin.touch()
    monkeypatch.setattr(scheduler.shutil, "which", lambda _name: None)
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    run = FakeRun(stdout="Running|267009|2026-10-29 18:35")

    task_info(TELEGRAM_TASK, run=run)

    assert run.calls[0][0] == str(builtin)


def test_missing_powershell_raises_scheduler_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scheduler.shutil, "which", lambda _name: None)
    monkeypatch.setenv("SystemRoot", str(tmp_path))

    with pytest.raises(SchedulerError, match="PowerShell"):
        task_info(TELEGRAM_TASK, run=FakeRun())


@pytest.mark.parametrize(
    ("code", "expected"),
    [(0, "correcta"), (0x41303, "todavía no"), (0x80070002, "no se encontró el programa"), (1, "código 0x1")],
)
def test_describe_result(code: int, expected: str) -> None:
    assert expected in describe_result(code)


# --- Comando y cron ---------------------------------------------------------


def test_jarvis_command_prefers_pythonw(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.touch()
    (tmp_path / "pythonw.exe").touch()

    command = jarvis_command(Path("/proyecto"), TELEGRAM_ARGUMENTS, python=python)

    assert command.executable == tmp_path / "pythonw.exe"
    assert command.arguments == "-m jarvis telegram --programado"


def test_jarvis_command_falls_back_to_python(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.touch()

    assert jarvis_command(Path("/proyecto"), SUMMARY_ARGUMENTS, python=python).executable == python


def test_cron_lines() -> None:
    command = ScheduledCommand(Path("/home/yo/jarvis/.venv/bin/python"), SUMMARY_ARGUMENTS, Path("/home/yo/mi jarvis"))

    assert cron_line(command, time(7, 5)) == (
        "5 7 * * 1-5 cd '/home/yo/mi jarvis' && /home/yo/jarvis/.venv/bin/python -m jarvis resumen --programado"
    )
    assert cron_reboot_line(command).startswith("@reboot cd '/home/yo/mi jarvis' && ")
