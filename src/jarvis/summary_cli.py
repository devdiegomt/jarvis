"""Comandos de consola del resumen diario: enviarlo, programarlo y quitar la programación."""

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import NoReturn

import anthropic

from jarvis.agenda import CalendarError, CalendarSource, build_calendar
from jarvis.config import SUMMARY_LOG_FILE, ConfigError, Settings, load_settings
from jarvis.notify import ConsoleNotifier, NotificationError, Notifier
from jarvis.storage import SummaryLog
from jarvis.summary import DailySummary, run_with_retries, send_daily_summary

PROJECT_DIR = Path(__file__).resolve().parents[2]

# En modo programado se reintenta ante fallos temporales (por ejemplo, sin red al encender).
SCHEDULED_ATTEMPTS = 4  # el primero + 3 reintentos
SCHEDULED_RETRY_WAIT_SECONDS = 10 * 60

logger = logging.getLogger("jarvis.resumen")
# Sin archivo de log configurado (modo prueba), los mensajes no se duplican en la consola.
logger.addHandler(logging.NullHandler())


def run_summary(dry_run: bool, force: bool, scheduled: bool) -> None:
    """`jarvis resumen`. Con `pythonw` no hay consola: el resultado queda en el log."""
    if not dry_run:
        _setup_log_file()
    settings = _load_settings_or_exit()
    if not dry_run and not settings.summary.enabled:
        _fail("Define JARVIS_RESUMEN_DESTINATARIO en tu .env para enviar el resumen.")

    calendar = _build_calendar_or_exit(settings)
    day = datetime.now(settings.timezone).date()

    def attempt() -> DailySummary | None:
        return send_daily_summary(
            day=day,
            calendar=calendar,
            notifier=ConsoleNotifier() if dry_run else _gmail_notifier(settings),
            client=anthropic.Anthropic(api_key=settings.api_key),
            model=settings.model,
            log=None if dry_run else SummaryLog(settings.summary.db_path),
            now=lambda: datetime.now(settings.timezone),
            force=force,
        )

    def on_retry(attempt_number: int, exc: Exception) -> None:
        minutes = SCHEDULED_RETRY_WAIT_SECONDS // 60
        logger.warning("Intento %d fallido (%s). Reintento en %d min.", attempt_number, exc, minutes)

    try:
        summary = run_with_retries(
            attempt,
            attempts=SCHEDULED_ATTEMPTS if scheduled else 1,
            wait_seconds=SCHEDULED_RETRY_WAIT_SECONDS,
            on_retry=on_retry,
        )
    except (CalendarError, NotificationError) as exc:
        _fail(f"No se pudo enviar el resumen: {exc}")
    except Exception:
        logger.exception("Error inesperado al enviar el resumen del %s.", day)
        raise

    if dry_run:
        print("\n(Modo prueba: no se envió nada.)")
    elif summary is None:
        logger.info("Resumen del %s ya enviado; no se reenvía.", day)
        print("El resumen de hoy ya se había enviado. Usa --force para reenviarlo.")
    else:
        logger.info(
            "Resumen del %s enviado (%d reuniones, comentario de IA: %s).",
            day, summary.meetings_count, "sí" if summary.ai_generated else "no",
        )
        print(f"Resumen enviado a {settings.summary.recipient}.")


def run_schedule_install() -> None:
    """`jarvis programar-resumen`: comprueba la configuración y registra la tarea."""
    from jarvis.google_auth import GMAIL_SEND_SCOPE, GoogleAuthError, load_credentials
    from jarvis.scheduler import SchedulerError, cron_line, install_windows_task, summary_command

    settings = _load_settings_or_exit()
    if not settings.summary.enabled:
        _fail("Define JARVIS_RESUMEN_DESTINATARIO en tu .env antes de programar el resumen.")
    try:
        load_credentials(settings.google.token_file, [GMAIL_SEND_SCOPE])
    except GoogleAuthError as exc:
        _fail(str(exc))
    if settings.calendar_source == "sample":
        print("Aviso: JARVIS_CALENDAR=sample, así que el resumen usará reuniones de ejemplo.")

    command = summary_command(PROJECT_DIR)
    hour = f"{settings.summary.send_time:%H:%M}"
    if os.name != "nt":
        print("La programación automática solo está disponible en Windows.")
        print(f"Agrega esta línea a tu crontab (`crontab -e`) para recibirlo a las {hour}:")
        print(cron_line(command, settings.summary.send_time))
        return

    tomorrow = datetime.now(settings.timezone).date() + timedelta(days=1)
    try:
        install_windows_task(command, settings.summary.send_time, tomorrow)
    except SchedulerError as exc:
        _fail(str(exc))
    print(f"Listo: recibirás el resumen de lunes a viernes a las {hour} en {settings.summary.recipient}.")
    print("Lo verás en el Programador de tareas de Windows, carpeta JARVIS.")
    print("Corre solo con tu sesión iniciada; si el PC estaba apagado, se ejecuta al encenderlo.")


def run_schedule_remove() -> None:
    """`jarvis quitar-resumen`."""
    from jarvis.scheduler import SchedulerError, remove_windows_task

    if os.name != "nt":
        print("En Mac o Linux, quita la línea de JARVIS de tu crontab con `crontab -e`.")
        return
    try:
        remove_windows_task()
    except SchedulerError as exc:
        _fail(str(exc))
    print("Listo: ya no se enviará el resumen diario.")


def _gmail_notifier(settings: Settings) -> Notifier:
    from jarvis.notify.gmail import GmailNotifier, gmail_service_factory

    return GmailNotifier(gmail_service_factory(settings.google.token_file), settings.summary.recipient)


def _load_settings_or_exit() -> Settings:
    try:
        return load_settings()
    except ConfigError as exc:
        _fail(f"Error de configuración: {exc}")


def _build_calendar_or_exit(settings: Settings) -> CalendarSource:
    try:
        return build_calendar(settings)
    except ConfigError as exc:
        _fail(f"Error de configuración: {exc}")


def _fail(message: str) -> NoReturn:
    logger.error(message)
    print(message, file=sys.stderr)
    sys.exit(1)


def _setup_log_file(log_file: Path = SUMMARY_LOG_FILE) -> None:
    if any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        return
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
