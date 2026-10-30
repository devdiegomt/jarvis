from pathlib import Path

from jarvis.scheduler import SUMMARY_TASK, TELEGRAM_TASK, SchedulerError, TaskInfo
from jarvis.status import status_report

FULL_ENV = {
    "ANTHROPIC_API_KEY": "sk-test",
    "JARVIS_CALENDAR": "sample",
    "JARVIS_RESUMEN_CANAL": "telegram",
    "JARVIS_RESUMEN_HORA": "07:00",
    "TELEGRAM_BOT_TOKEN": "123456:ABC-def",
    "TELEGRAM_OWNER_ID": "987654321",
}


def states(summary: str | None, telegram: str | None, telegram_result: int = 0):  # type: ignore[no-untyped-def]
    infos = {
        SUMMARY_TASK: TaskInfo(summary, 0, "2026-10-30 07:00") if summary else None,
        TELEGRAM_TASK: TaskInfo(telegram, telegram_result, "2026-10-29 18:35") if telegram else None,
    }
    return lambda name: infos[name]


def report(env: dict[str, str], read_task_info, logs: dict[str, Path] | None = None) -> str:  # type: ignore[no-untyped-def]
    return "\n".join(status_report(env, read_task_info, logs or {}))


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
    text = report(FULL_ENV, states(None, "Ready", telegram_result=1))

    assert "Resumen diario: no programada" in text
    assert "Última ejecución: 2026-10-29 18:35 (terminó con error (código 0x1))" in text
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


def test_pending_reminders_show_count_and_next_time_only(isolated_config_dir: Path) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from jarvis.reminders import ReminderStore

    tz = ZoneInfo("America/Bogota")
    store = ReminderStore(isolated_config_dir / "jarvis.db", now=lambda: datetime(2026, 10, 30, 8, 0, tzinfo=tz))
    store.create("llamar a Laura", datetime(2026, 10, 30, 9, 0, tzinfo=tz))
    store.create("pagar la factura", datetime(2026, 10, 31, 10, 0, tzinfo=tz))

    text = report({**FULL_ENV, "JARVIS_TIMEZONE": "America/Bogota"}, None)

    assert "Recordatorios pendientes: 2 (el próximo: 2026-10-30 09:00)" in text
    assert "Laura" not in text  # el texto de los recordatorios no se muestra


def test_status_does_not_create_the_database(isolated_config_dir: Path) -> None:
    text = report(FULL_ENV, None)

    assert "Recordatorios pendientes: ninguno" in text
    assert not (isolated_config_dir / "jarvis.db").exists()


def test_voice_status_is_shown(isolated_config_dir: Path) -> None:
    text = report({**FULL_ENV, "JARVIS_TRANSCRIPCION": "no"}, None)

    assert "Notas de voz: desactivadas" in text


def test_speech_status_is_shown(isolated_config_dir: Path) -> None:
    text = report({**FULL_ENV, "JARVIS_RESPUESTA_VOZ": "no"}, None)

    assert "Respuestas con voz: desactivadas" in text
