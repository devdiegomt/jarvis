"""Carga de configuración desde variables de entorno y el archivo .env."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

DEFAULT_MODEL = "claude-sonnet-5-5"
CALENDAR_SOURCES = ("sample", "google")
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "jarvis"
DEFAULT_SUMMARY_TIME = time(7, 0)
# Registros de ejecución: solo resultados, nunca el contenido de los mensajes.
SUMMARY_LOG_FILE = DEFAULT_CONFIG_DIR / "logs" / "resumen.log"
WHATSAPP_LOG_FILE = DEFAULT_CONFIG_DIR / "logs" / "whatsapp.log"
DEFAULT_WHATSAPP_PORT = 8000
DEFAULT_WHATSAPP_API_VERSION = "v25.0"


class ConfigError(Exception):
    """La configuración es inválida o está incompleta."""


@dataclass(frozen=True)
class GoogleSettings:
    credentials_file: Path
    token_file: Path
    calendar_id: str


@dataclass(frozen=True)
class SummarySettings:
    """Resumen diario por correo. `recipient` vacío significa que está desactivado."""

    recipient: str
    send_time: time
    db_path: Path

    @property
    def enabled(self) -> bool:
        return bool(self.recipient)


@dataclass(frozen=True)
class WhatsAppSettings:
    access_token: str
    phone_number_id: str
    app_secret: str
    verify_token: str
    owner_number: str  # solo dígitos, con código de país (ej. 573001234567)
    port: int
    api_version: str


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    timezone: tzinfo
    calendar_source: str
    google: GoogleSettings
    summary: SummarySettings


def read_env() -> Mapping[str, str]:
    """Variables de entorno, completadas con el archivo .env si existe."""
    load_dotenv()
    return os.environ


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Configuración completa para el chat."""
    env = read_env() if env is None else env
    api_key = _get(env, "ANTHROPIC_API_KEY")
    if not api_key:
        raise ConfigError(
            "Falta ANTHROPIC_API_KEY. Copia .env.example a .env y completa tu API key."
        )
    return Settings(
        api_key=api_key,
        model=_get(env, "JARVIS_MODEL") or DEFAULT_MODEL,
        timezone=load_timezone(env),
        calendar_source=_load_calendar_source(env),
        google=load_google_settings(env),
        summary=load_summary_settings(env),
    )


def load_timezone(env: Mapping[str, str]) -> tzinfo:
    """Zona horaria IANA de JARVIS_TIMEZONE; si está vacía, la del sistema."""
    name = _get(env, "JARVIS_TIMEZONE")
    if not name:
        system_tz = datetime.now().astimezone().tzinfo
        assert system_tz is not None
        return system_tz
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(
            f"JARVIS_TIMEZONE='{name}' no es una zona horaria válida. "
            "Usa un nombre IANA, por ejemplo America/Bogota."
        ) from exc


def load_google_settings(env: Mapping[str, str]) -> GoogleSettings:
    return GoogleSettings(
        credentials_file=_path(env, "GOOGLE_CREDENTIALS_FILE", DEFAULT_CONFIG_DIR / "credentials.json"),
        token_file=_path(env, "GOOGLE_TOKEN_FILE", DEFAULT_CONFIG_DIR / "token.json"),
        calendar_id=_get(env, "GOOGLE_CALENDAR_ID") or "primary",
    )


def load_summary_settings(env: Mapping[str, str]) -> SummarySettings:
    recipient = _get(env, "JARVIS_RESUMEN_DESTINATARIO")
    if recipient and ("@" not in recipient or " " in recipient):
        raise ConfigError(f"JARVIS_RESUMEN_DESTINATARIO='{recipient}' no parece un correo válido.")
    return SummarySettings(
        recipient=recipient,
        send_time=_load_time(env, "JARVIS_RESUMEN_HORA", DEFAULT_SUMMARY_TIME),
        db_path=_path(env, "JARVIS_DB_PATH", DEFAULT_CONFIG_DIR / "jarvis.db"),
    )


def load_whatsapp_settings(env: Mapping[str, str]) -> WhatsAppSettings:
    """Configuración del canal de WhatsApp. Todas las credenciales son obligatorias."""
    required = {
        name: _get(env, name)
        for name in (
            "WHATSAPP_ACCESS_TOKEN",
            "WHATSAPP_PHONE_NUMBER_ID",
            "WHATSAPP_APP_SECRET",
            "WHATSAPP_VERIFY_TOKEN",
            "WHATSAPP_OWNER_NUMBER",
        )
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ConfigError(f"Faltan variables de WhatsApp en tu .env: {', '.join(missing)}.")

    owner = normalize_phone(required["WHATSAPP_OWNER_NUMBER"])
    if not 8 <= len(owner) <= 15:
        raise ConfigError(
            "WHATSAPP_OWNER_NUMBER debe ser tu número con código de país, por ejemplo 573001234567."
        )
    port_text = _get(env, "WHATSAPP_PORT") or str(DEFAULT_WHATSAPP_PORT)
    if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
        raise ConfigError(f"WHATSAPP_PORT='{port_text}' no es un puerto válido.")

    return WhatsAppSettings(
        access_token=required["WHATSAPP_ACCESS_TOKEN"],
        phone_number_id=required["WHATSAPP_PHONE_NUMBER_ID"],
        app_secret=required["WHATSAPP_APP_SECRET"],
        verify_token=required["WHATSAPP_VERIFY_TOKEN"],
        owner_number=owner,
        port=int(port_text),
        api_version=_get(env, "WHATSAPP_API_VERSION") or DEFAULT_WHATSAPP_API_VERSION,
    )


def normalize_phone(number: str) -> str:
    """Deja solo los dígitos: `+57 300-123 4567` → `573001234567`."""
    return "".join(char for char in number if char.isdigit())


def _load_time(env: Mapping[str, str], name: str, default: time) -> time:
    value = _get(env, name)
    if not value:
        return default
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise ConfigError(
            f"{name}='{value}' no es una hora válida. Usa el formato HH:MM, por ejemplo 07:00."
        ) from exc


def _load_calendar_source(env: Mapping[str, str]) -> str:
    source = (_get(env, "JARVIS_CALENDAR") or "sample").lower()
    if source not in CALENDAR_SOURCES:
        raise ConfigError(
            f"JARVIS_CALENDAR='{source}' no es válido. Opciones: {', '.join(CALENDAR_SOURCES)}."
        )
    return source


def _get(env: Mapping[str, str], name: str) -> str:
    return env.get(name, "").strip()


def _path(env: Mapping[str, str], name: str, default: Path) -> Path:
    value = _get(env, name)
    return Path(value).expanduser() if value else default
