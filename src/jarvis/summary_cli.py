"""Comandos de consola del resumen diario: enviarlo, programarlo y quitar la programación."""

import logging
import os
import sys
from datetime import datetime, timedelta
from typing import NoReturn

import anthropic

from jarvis.agenda import CalendarError, CalendarSource, build_calendar
from jarvis.config import (
    SUMMARY_LOG_FILE,
    ConfigError,
    Settings,
    TelegramSettings,
    load_settings,
    load_telegram_settings,
    read_env,
)
from jarvis.logs import FILE_ONLY, setup_logger
from jarvis.notify import ConsoleNotifier, NotificationError, Notifier
from jarvis.storage import SummaryLog
from jarvis.summary import DailySummary, run_with_retries, send_daily_summary

# En modo programado se reintenta ante fallos temporales (por ejemplo, sin red al encender).
SCHEDULED_ATTEMPTS = 4  # el primero + 3 reintentos
SCHEDULED_RETRY_WAIT_SECONDS = 10 * 60

logger = logging.getLogger("jarvis.resumen")
# Sin archivo de log configurado (modo prueba), los mensajes no se duplican en la consola.
logger.addHandler(logging.NullHandler())

DISABLED_MESSAGE = (
    "El resumen no está configurado: usa JARVIS_RESUMEN_CANAL=telegram, o define "
    "JARVIS_RESUMEN_DESTINATARIO para recibirlo por Gmail."
)


def run_summary(dry_run: bool, force: bool, scheduled: bool) -> None:
    """`jarvis resumen`. Con `pythonw` no hay consola: el resultado queda en el log."""
    if not dry_run:
        setup_logger(logger, SUMMARY_LOG_FILE, console=False)
    settings = _load_settings_or_exit()
    if not dry_run and not settings.summary.enabled:
        _fail(DISABLED_MESSAGE)

    calendar = _build_calendar_or_exit(settings)
    notifier = ConsoleNotifier() if dry_run else _build_notifier(settings)
    day = datetime.now(settings.timezone).date()

    def attempt() -> DailySummary | None:
        return send_daily_summary(
            day=day,
            calendar=calendar,
            notifier=notifier,
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
        channel = _destination(settings) if settings.summary.enabled else "ninguno"
        print(f"\n(Modo prueba: no se envió nada. Canal configurado: {channel}.)")
        if not settings.summary.enabled:
            print(DISABLED_MESSAGE)
    elif summary is None:
        logger.info("Resumen del %s ya enviado; no se reenvía.", day)
        print("El resumen de hoy ya se había enviado. Usa --force para reenviarlo.")
    else:
        logger.info(
            "Resumen del %s enviado (%d reuniones, comentario de IA: %s).",
            day, summary.meetings_count, "sí" if summary.ai_generated else "no",
        )
        print(f"Resumen enviado por {_destination(settings)}.")


def run_schedule_install() -> None:
    """`jarvis programar-resumen`: comprueba la configuración y registra la tarea."""
    from jarvis.scheduler import (
        PROJECT_DIR,
        SUMMARY_ARGUMENTS,
        SUMMARY_TASK,
        SchedulerError,
        cron_line,
        install_task,
        jarvis_command,
        summary_task_xml,
        windows_user,
    )

    settings = _load_settings_or_exit()
    if not settings.summary.enabled:
        _fail(DISABLED_MESSAGE)
    _check_channel_ready(settings)
    if settings.calendar_source == "sample":
        print("Aviso: JARVIS_CALENDAR=sample, así que el resumen usará reuniones de ejemplo.")

    command = jarvis_command(PROJECT_DIR, SUMMARY_ARGUMENTS)
    hour = f"{settings.summary.send_time:%H:%M}"
    if os.name != "nt":
        print("La programación automática solo está disponible en Windows.")
        print(f"Agrega esta línea a tu crontab (`crontab -e`) para recibirlo a las {hour}:")
        print(cron_line(command, settings.summary.send_time))
        return

    tomorrow = datetime.now(settings.timezone).date() + timedelta(days=1)
    try:
        xml = summary_task_xml(command, settings.summary.send_time, tomorrow, windows_user())
        install_task(SUMMARY_TASK, xml)
    except SchedulerError as exc:
        _fail(str(exc))
    print(f"Listo: recibirás el resumen de lunes a viernes a las {hour} por {_destination(settings)}.")
    print("Lo verás en el Programador de tareas de Windows, carpeta JARVIS.")
    print("Corre solo con tu sesión iniciada; si el PC estaba apagado, se ejecuta al encenderlo.")


def run_schedule_remove() -> None:
    """`jarvis quitar-resumen`."""
    from jarvis.scheduler import SUMMARY_TASK, SchedulerError, remove_task

    if os.name != "nt":
        print("En Mac o Linux, quita la línea de JARVIS de tu crontab con `crontab -e`.")
        return
    try:
        remove_task(SUMMARY_TASK)
    except SchedulerError as exc:
        _fail(str(exc))
    print("Listo: ya no se enviará el resumen diario.")


def _build_notifier(settings: Settings) -> Notifier:
    if settings.summary.channel == "telegram":
        from jarvis.notify.telegram import TelegramNotifier
        from jarvis.telegram.client import TelegramClient

        telegram = _load_telegram_or_exit()
        assert telegram.owner_id is not None
        return TelegramNotifier(TelegramClient(telegram.bot_token), telegram.owner_id)

    from jarvis.notify.gmail import GmailNotifier, gmail_service_factory

    return GmailNotifier(gmail_service_factory(settings.google.token_file), settings.summary.recipient)


def _check_channel_ready(settings: Settings) -> None:
    """Antes de programar, comprueba que el canal del resumen esté listo para enviar."""
    if settings.summary.channel == "telegram":
        from jarvis.telegram.client import TelegramClient, TelegramError

        telegram = _load_telegram_or_exit()
        try:
            TelegramClient(telegram.bot_token).get_me()
        except TelegramError as exc:
            _fail(f"Error de Telegram: {exc}")
        return

    from jarvis.google_auth import GMAIL_SEND_SCOPE, GoogleAuthError, load_credentials

    try:
        load_credentials(settings.google.token_file, [GMAIL_SEND_SCOPE])
    except GoogleAuthError as exc:
        _fail(str(exc))


def _destination(settings: Settings) -> str:
    if settings.summary.channel == "telegram":
        return "Telegram"
    return f"Gmail a {settings.summary.recipient}"


def _load_telegram_or_exit() -> TelegramSettings:
    try:
        return load_telegram_settings(read_env())
    except ConfigError as exc:
        _fail(f"Error de configuración: {exc}")


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
    logger.error(message, extra=FILE_ONLY)
    print(message, file=sys.stderr)
    sys.exit(1)

