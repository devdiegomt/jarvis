"""Carga de configuración desde variables de entorno y el archivo .env."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_MODEL = "claude-sonnet-5-5"


class ConfigError(Exception):
    """La configuración es inválida o está incompleta."""


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str


def load_settings() -> Settings:
    """Lee la configuración del entorno (y de .env si existe)."""
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise ConfigError(
            "Falta ANTHROPIC_API_KEY. Copia .env.example a .env y completa tu API key."
        )
    model = os.getenv("JARVIS_MODEL", "").strip() or DEFAULT_MODEL
    return Settings(api_key=api_key, model=model)
