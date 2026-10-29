"""Carga de configuración desde variables de entorno y el archivo .env."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

DEFAULT_MODEL = "claude-sonnet-5-5"
CALENDAR_SOURCES = ("sample", "google")
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "jarvis"


class ConfigError(Exception):
    """La configuración es inválida o está incompleta."""


@dataclass(frozen=True)
class GoogleSettings:
    credentials_file: Path
    token_file: Path
    calendar_id: str


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    timezone: tzinfo
    calendar_source: str
    google: GoogleSettings


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
