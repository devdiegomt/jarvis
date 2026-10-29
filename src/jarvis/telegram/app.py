"""Comandos de Telegram.

- `jarvis telegram`: chat con JARVIS (en una terminal o, con `--programado`, en segundo plano).
- `jarvis telegram-vincular`: obtener tu ID para TELEGRAM_OWNER_ID.
- `jarvis programar-telegram` / `quitar-telegram`: arrancar JARVIS al iniciar sesión en Windows.
"""

import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, NoReturn

import anthropic

from jarvis.agent import Agent
from jarvis.agenda import CalendarSource, build_calendar
from jarvis.chat import COMMANDS, ChatService
from jarvis.config import (
    TELEGRAM_LOG_FILE,
    ConfigError,
    Settings,
    TelegramSettings,
    load_settings,
    load_telegram_settings,
    read_env,
)
from jarvis.logs import FILE_ONLY, setup_logger
from jarvis.memory import ConversationStore
from jarvis.prompts import build_chat_system_prompt
from jarvis.telegram.bot import (
    MAX_BACKOFF_SECONDS,
    TelegramChannel,
    TelegramPoller,
    wait_for_first_message,
)
from jarvis.telegram.client import (
    TelegramClient,
    TelegramConflictError,
    TelegramConnectionError,
    TelegramError,
)
from jarvis.tools import Confirmer, build_registry

LINK_TIMEOUT_SECONDS = 5 * 60
BACKGROUND_HINT = (
    "Si programaste JARVIS con `programar-telegram`, ya está corriendo en segundo plano: "
    "no hace falta abrirlo a mano. Para detenerlo: `uv run jarvis quitar-telegram`."
)

logger = logging.getLogger("jarvis.chat")


def run_telegram(scheduled: bool = False) -> None:
    """Chat por Telegram. En modo programado no hay consola: todo queda en el log."""
    setup_logger(logger, TELEGRAM_LOG_FILE, console=not scheduled)
    settings, telegram = _load_or_exit(require_owner=True)
    assert settings is not None and telegram.owner_id is not None
    calendar = _build_calendar_or_exit(settings)
    client = TelegramClient(telegram.bot_token)
    # En segundo plano la red puede tardar en estar lista tras encender o despertar el PC.
    bot_name = _prepare_bot_or_exit(client, wait_for_network=scheduled)

    def now() -> datetime:
        return datetime.now(settings.timezone)

    store = ConversationStore(settings.summary.db_path, now=now)
    anthropic_client = anthropic.Anthropic(api_key=settings.api_key)

    def agent_factory(history: list, system_prompt: str, confirm: Confirmer) -> Agent:
        return Agent(
            client=anthropic_client,
            registry=build_registry(calendar=calendar, confirm=confirm),
            model=settings.model,
            system_prompt=system_prompt,
            history=history,
        )

    chat = ChatService(
        channel=TelegramChannel(client),
        store=store,
        agent_factory=agent_factory,
        system_prompt=lambda: build_chat_system_prompt(now().date()),
        now=now,
    )
    poller = TelegramPoller(client, telegram.owner_id, deliver=chat.submit, mark_processed=store.mark_processed)
    chat.start()

    print(f"JARVIS conectado a Telegram como @{bot_name} (calendario: {calendar.name}).")
    print("Escríbele a tu bot desde Telegram. Ctrl+C para detener.\n")
    logger.info("Bot de Telegram iniciado%s.", " en segundo plano" if scheduled else "")
    try:
        poller.run_forever(wait_on_conflict=scheduled)
    except KeyboardInterrupt:
        print("\nJARVIS desconectado.")
    except TelegramConflictError as exc:
        _fail(f"Error de Telegram: {exc} {BACKGROUND_HINT}")
    except TelegramError as exc:
        _fail(f"El bot se detuvo. Error de Telegram: {exc}")
    finally:
        logger.info("Bot de Telegram detenido.")


def run_link() -> None:
    """Espera un mensaje al bot y muestra el ID de quien lo envió, para TELEGRAM_OWNER_ID."""
    _, telegram = _load_or_exit(require_owner=False, need_settings=False)
    client = TelegramClient(telegram.bot_token)
    bot_name = _prepare_bot_or_exit(client)

    print(f"Abre Telegram, busca @{bot_name} y envíale /start.")
    print("Esperando tu mensaje (hasta 5 minutos; Ctrl+C para cancelar)…\n")
    try:
        user = wait_for_first_message(client, LINK_TIMEOUT_SECONDS)
    except KeyboardInterrupt:
        print("\nCancelado.")
        return
    except TelegramConflictError as exc:
        _fail(f"Error de Telegram: {exc} {BACKGROUND_HINT}")
    except TelegramError as exc:
        _fail(f"Error de Telegram: {exc}")
    if user is None:
        _fail("No llegó ningún mensaje en 5 minutos. Vuelve a intentarlo.")
    _print_link_result(user)


def run_schedule_install() -> None:
    """`jarvis programar-telegram`: arranca JARVIS al iniciar sesión, y también ahora mismo."""
    from jarvis.scheduler import (
        PROJECT_DIR,
        TELEGRAM_ARGUMENTS,
        TELEGRAM_TASK,
        SchedulerError,
        cron_reboot_line,
        install_task,
        jarvis_command,
        start_task,
        telegram_task_xml,
        windows_user,
    )

    _, telegram = _load_or_exit(require_owner=True)
    _prepare_bot_or_exit(TelegramClient(telegram.bot_token))  # comprueba el token antes de programar
    command = jarvis_command(PROJECT_DIR, TELEGRAM_ARGUMENTS)

    if os.name != "nt":
        print("El arranque automático solo está disponible en Windows.")
        print("Agrega esta línea a tu crontab (`crontab -e`) para arrancarlo al encender el equipo:")
        print(cron_reboot_line(command))
        return

    try:
        install_task(TELEGRAM_TASK, telegram_task_xml(command, windows_user()))
        start_task(TELEGRAM_TASK)
    except SchedulerError as exc:
        _fail(str(exc))
    print("Listo: JARVIS ya corre en segundo plano y arrancará solo al iniciar sesión en Windows.")
    print("Escríbele a tu bot para comprobarlo. Si tenías `jarvis telegram` abierto, ciérralo.")
    print("Para ver cómo va: `uv run jarvis estado`.")


def run_schedule_remove() -> None:
    """`jarvis quitar-telegram`: detiene JARVIS en segundo plano y quita el arranque automático."""
    from jarvis.scheduler import TELEGRAM_TASK, SchedulerError, remove_task, stop_task, task_state

    if os.name != "nt":
        print("En Mac o Linux, quita la línea de JARVIS de tu crontab con `crontab -e`.")
        return
    try:
        if task_state(TELEGRAM_TASK) == "Running":
            stop_task(TELEGRAM_TASK)
        remove_task(TELEGRAM_TASK)
    except SchedulerError as exc:
        _fail(str(exc))
    print("Listo: JARVIS ya no corre en segundo plano ni arrancará al iniciar sesión.")


def _print_link_result(user: dict[str, Any]) -> None:
    name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or "tu cuenta"
    print(f"Mensaje recibido de {name}.")
    print(f"Agrega esta línea a tu .env:\n\nTELEGRAM_OWNER_ID={user['id']}\n")
    print("Después ejecuta `uv run jarvis telegram`.")


def _prepare_bot_or_exit(client: TelegramClient, wait_for_network: bool = False) -> str:
    """Comprueba el token, desactiva cualquier webhook y registra el menú de comandos."""
    backoff = 1.0
    while True:
        try:
            bot = client.get_me()
            client.delete_webhook()
            client.set_commands(COMMANDS)
            return str(bot.get("username", "tu_bot"))
        except TelegramConnectionError as exc:
            if not wait_for_network:
                _fail(f"Error de Telegram: {exc}")
            logger.warning("%s Reintento en %.0f s.", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
        except TelegramError as exc:
            _fail(f"Error de Telegram: {exc}")


def _load_or_exit(
    require_owner: bool, need_settings: bool = True
) -> tuple[Settings | None, TelegramSettings]:
    try:
        env = read_env()
        settings = load_settings(env) if need_settings else None
        return settings, load_telegram_settings(env, require_owner=require_owner)
    except ConfigError as exc:
        _fail(f"Error de configuración: {exc}")


def _build_calendar_or_exit(settings: Settings) -> CalendarSource:
    try:
        return build_calendar(settings)
    except ConfigError as exc:
        _fail(f"Error de configuración: {exc}")


def _fail(message: str) -> NoReturn:
    """Termina con error. Queda en el log por si no hay consola (modo programado)."""
    logger.error(message, extra=FILE_ONLY)
    print(message, file=sys.stderr)
    sys.exit(1)
