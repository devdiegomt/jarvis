"""Arranque de la API para el iPhone y sus comandos (`api-clave` y `app`)."""

import logging
import sys
from collections.abc import Callable

from jarvis.api.auth import KeyChecker, generate_key, has_key
from jarvis.api.channel import ApiChannel, ChatBridge
from jarvis.api.server import ApiServer
from jarvis.assistant import Assistant
from jarvis.chat import ChatService
from jarvis.config import ApiSettings, ConfigError, load_api_settings, read_env
from jarvis.prompts import build_chat_system_prompt
from jarvis.quick import today_data

logger = logging.getLogger("jarvis.chat")

NO_KEY_TEXT = "La app del iPhone no arrancó: falta la clave. Créala con «jarvis api-clave»."


def start_api(assistant: Assistant, quick_commands: dict[str, Callable[[], str]]) -> ApiServer | None:
    """Arranca la API dentro del proceso de JARVIS. Si no puede, lo registra y JARVIS sigue sin ella."""
    settings = assistant.settings
    api = settings.api
    if not has_key(api.key_file):
        logger.warning(NO_KEY_TEXT)
        return None

    channel = ApiChannel()
    chat = ChatService(
        channel=channel,
        store=assistant.conversations,
        agent_factory=assistant.agent_factory,
        system_prompt=lambda: build_chat_system_prompt(
            assistant.now().date(),
            assistant.memories.all(),
            settings.web,
            mail=assistant.mail is not None,
            weather=assistant.weather is not None,
        ),
        now=assistant.now,
        memories=assistant.memories,
        watched=assistant.watched,
        usage_log=assistant.usage,
        quick_commands=quick_commands,
    )
    try:
        server = ApiServer(
            port=api.port,
            checker=KeyChecker(api.key_file),
            bridge=ChatBridge(channel, chat.submit),
            quick_commands=quick_commands,
            today=lambda: today_data(
                calendar=assistant.calendar,
                tasks=assistant.tasks,
                reminders=assistant.reminders,
                weather=assistant.weather,
                now=assistant.now(),
                timezone=settings.timezone,
            ),
            tailscale_user=api.tailscale_user,
        )
    except OSError as exc:
        logger.error("La app del iPhone no arrancó: el puerto %d no está libre (%s).", api.port, exc)
        return None
    chat.start()
    server.start()
    logger.info("App del iPhone escuchando en 127.0.0.1:%d (publícala con tailscale serve).", api.port)
    return server


def describe_api(api: ApiSettings) -> str:
    """Para `estado` y el arranque."""
    if not api.enabled:
        return "desactivada (JARVIS_API=si la activa)"
    if not has_key(api.key_file):
        return "⚠ falta la clave: ejecuta «jarvis api-clave»"
    user = f", solo la cuenta {api.tailscale_user}" if api.tailscale_user else ""
    return f"activa en 127.0.0.1:{api.port}{user} (publícala con «tailscale serve --bg {api.port}»)"


def run_api_key() -> None:
    """`jarvis api-clave`: crea una clave nueva para la app del iPhone."""
    try:
        api = load_api_settings(read_env())
    except ConfigError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        sys.exit(1)
    replacing = has_key(api.key_file)
    key = generate_key(api.key_file)
    print("Clave de la app de JARVIS (cópiala ahora: no se vuelve a mostrar):\n")
    print(f"    {key}\n")
    if replacing:
        print("La clave anterior dejó de servir: vuelve a entrar en la app con esta.")
    print("En el equipo solo se guarda su huella, no la clave. Si la pierdes, crea otra.")
    if not api.enabled:
        print("Recuerda activar la app con JARVIS_API=si en tu .env y reiniciar JARVIS.")
