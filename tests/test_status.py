from pathlib import Path

from jarvis.scheduler import SUMMARY_TASK, TELEGRAM_TASK, SchedulerError
from jarvis.status import status_report

FULL_ENV = {
    "ANTHROPIC_API_KEY": "sk-test",
    "JARVIS_CALENDAR": "sample",
    "JARVIS_RESUMEN_CANAL": "telegram",
    "JARVIS_RESUMEN_HORA": "07:00",
    "TELEGRAM_BOT_TOKEN": "123456:ABC-def",
    "TELEGRAM_OWNER_ID": "987654321",
}


def states(summary: str | None, telegram: str | None):  # type: ignore[no-untyped-def]
    return lambda name: {SUMMARY_TASK: summary, TELEGRAM_TASK: telegram}[name]


def report(env: dict[str, str], read_task_state, logs: dict[str, Path] | None = None) -> str:  # type: ignore[no-untyped-def]
    return "\n".join(status_report(env, read_task_state, logs or {}))


def test_full_status_on_windows(tmp_path: Path) -> None:
    log = tmp_path / "telegram.log"
    log.write_text("".join(f"línea {i}\n" for i in range(10)), encoding="utf-8")

    text = report(FULL_ENV, states("Ready", "Running"), {"Telegram": log})

    assert "Calendario: ejemplo (datos simulados)" in text
    assert "Resumen diario: Telegram, de lunes a viernes a las 07:00" in text
    assert "Telegram: bot configurado y cuenta vinculada" in text
    assert "Resumen diario: programada (en espera)" in text
    assert "Telegram en segundo plano: programada y en ejecución" in text
    assert "línea 9" in text and "línea 4" not in text  # solo las últimas 5 líneas


def test_telegram_task_not_running_gets_a_hint() -> None:
    text = report(FULL_ENV, states(None, "Ready"))

    assert "Resumen diario: no programada" in text
    assert "No está corriendo ahora" in text


def test_configuration_problems_are_shown_not_raised() -> None:
    text = report({"ANTHROPIC_API_KEY": "sk-test"}, states(None, None))

    assert "Resumen diario: no configurado" in text
    assert "Telegram: ⚠ Falta TELEGRAM_BOT_TOKEN" in text

    assert "Configuración: ⚠ Falta ANTHROPIC_API_KEY" in report({}, states(None, None))


def test_outside_windows_there_are_no_tasks(tmp_path: Path) -> None:
    text = report(FULL_ENV, None, {"Resumen": tmp_path / "no-existe.log"})

    assert "solo disponibles en Windows" in text
    assert "(sin registros todavía)" in text


def test_task_query_errors_are_reported() -> None:
    def failing(_name: str) -> str | None:
        raise SchedulerError("sin PowerShell")

    assert "no se pudo consultar (sin PowerShell)" in report(FULL_ENV, failing)
