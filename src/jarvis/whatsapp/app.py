"""Comando `jarvis whatsapp`: conecta el webhook, el worker y el agente, y arranca el servidor."""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import NoReturn

import anthropic

from jarvis.agent import Agent
from jarvis.agenda import CalendarSource, build_calendar
from jarvis.config import (
    WHATSAPP_LOG_FILE,
    ConfigError,
    Settings,
    WhatsAppSettings,
    load_settings,
    load_whatsapp_settings,
    read_env,
)
from jarvis.memory import ConversationStore
from jarvis.prompts import build_whatsapp_system_prompt
from jarvis.tools import Confirmer, build_registry
from jarvis.whatsapp.client import WhatsAppClient
from jarvis.whatsapp.webhook import WEBHOOK_PATH, WebhookConfig, build_server
from jarvis.whatsapp.worker import WhatsAppWorker

HOST = "127.0.0.1"  # solo local: ngrok es quien lo expone a internet

logger = logging.getLogger("jarvis.whatsapp")


def run_whatsapp() -> None:
    settings, whatsapp = _load_or_exit()
    _setup_logging()
    calendar = _build_calendar_or_exit(settings)

    def now() -> datetime:
        return datetime.now(settings.timezone)

    store = ConversationStore(settings.summary.db_path, now=now)
    client = WhatsAppClient(whatsapp.access_token, whatsapp.phone_number_id, whatsapp.api_version)
    anthropic_client = anthropic.Anthropic(api_key=settings.api_key)

    def agent_factory(history: list, system_prompt: str, confirm: Confirmer) -> Agent:
        return Agent(
            client=anthropic_client,
            registry=build_registry(calendar=calendar, confirm=confirm),
            model=settings.model,
            system_prompt=system_prompt,
            history=history,
        )

    worker = WhatsAppWorker(
        client=client,
        store=store,
        agent_factory=agent_factory,
        system_prompt=lambda: build_whatsapp_system_prompt(now().date()),
        now=now,
    )
    server = build_server(
        HOST,
        whatsapp.port,
        WebhookConfig(
            verify_token=whatsapp.verify_token,
            app_secret=whatsapp.app_secret,
            phone_number_id=whatsapp.phone_number_id,
            owner_number=whatsapp.owner_number,
            mark_processed=store.mark_processed,
            deliver=worker.submit,
        ),
    )
    worker.start()

    print(f"JARVIS escuchando en http://{HOST}:{whatsapp.port}{WEBHOOK_PATH} (calendario: {calendar.name}).")
    print(f"En otra terminal, expónlo con ngrok:  ngrok http --url=TU-DOMINIO.ngrok-free.app {whatsapp.port}")
    print("Ctrl+C para detener.\n")
    logger.info("Servidor de WhatsApp iniciado en el puerto %d.", whatsapp.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        server.server_close()
        logger.info("Servidor de WhatsApp detenido.")


def _load_or_exit() -> tuple[Settings, WhatsAppSettings]:
    try:
        return load_settings(), load_whatsapp_settings(read_env())
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


def _setup_logging(log_file: Path = WHATSAPP_LOG_FILE) -> None:
    """Log en archivo y en consola: solo IDs y resultados, nunca el texto de los mensajes."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
