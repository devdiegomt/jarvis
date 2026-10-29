"""Comandos `jarvis telegram` (chat con JARVIS) y `jarvis telegram-vincular` (obtener tu ID)."""

import logging
import sys
from datetime import datetime
from pathlib import Path
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
from jarvis.memory import ConversationStore
from jarvis.prompts import build_chat_system_prompt
from jarvis.telegram.bot import TelegramChannel, TelegramPoller, wait_for_first_message
from jarvis.telegram.client import TelegramClient, TelegramError
from jarvis.tools import Confirmer, build_registry

LINK_TIMEOUT_SECONDS = 5 * 60

logger = logging.getLogger("jarvis.chat")


def run_telegram() -> None:
    settings, telegram = _load_or_exit(require_owner=True)
    assert settings is not None and telegram.owner_id is not None
    _setup_logging()
    calendar = _build_calendar_or_exit(settings)
    client = TelegramClient(telegram.bot_token)
    bot_name = _prepare_bot_or_exit(client)

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
    logger.info("Bot de Telegram iniciado.")
    try:
        poller.run_forever()
    except KeyboardInterrupt:
        print("\nJARVIS desconectado.")
    except TelegramError as exc:
        logger.error("El bot se detuvo: %s", exc)
        _fail(f"Error de Telegram: {exc}")
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
    except TelegramError as exc:
        _fail(f"Error de Telegram: {exc}")
    if user is None:
        _fail("No llegó ningún mensaje en 5 minutos. Vuelve a intentarlo.")
    _print_link_result(user)


def _print_link_result(user: dict[str, Any]) -> None:
    name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or "tu cuenta"
    print(f"Mensaje recibido de {name}.")
    print(f"Agrega esta línea a tu .env:\n\nTELEGRAM_OWNER_ID={user['id']}\n")
    print("Después ejecuta `uv run jarvis telegram`.")


def _prepare_bot_or_exit(client: TelegramClient) -> str:
    """Comprueba el token, desactiva cualquier webhook y registra el menú de comandos."""
    try:
        bot = client.get_me()
        client.delete_webhook()
        client.set_commands(COMMANDS)
    except TelegramError as exc:
        _fail(f"Error de Telegram: {exc}")
    return str(bot.get("username", "tu_bot"))


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
    print(message, file=sys.stderr)
    sys.exit(1)


def _setup_logging(log_file: Path = TELEGRAM_LOG_FILE) -> None:
    """Log en archivo y en consola: solo IDs y resultados, nunca el texto de los mensajes."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
