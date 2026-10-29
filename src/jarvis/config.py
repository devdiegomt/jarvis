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
# Registro de ejecuciones del resumen: solo resultados, nunca el contenido.
SUMMARY_LOG_FILE = DEFAULT_CONFIG_DIR / "logs" / "resumen.log"


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
