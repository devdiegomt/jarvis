"""Carga de configuración desde variables de entorno y el archivo .env."""

import os
import re
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
TELEGRAM_LOG_FILE = DEFAULT_CONFIG_DIR / "logs" / "telegram.log"
SUMMARY_CHANNELS = ("gmail", "telegram")
# Transcripción de notas de voz: "local" (Whisper en el equipo) o "no" (desactivada).
TRANSCRIPTION_ENGINES = ("local", "no")
DEFAULT_WHISPER_MODEL = "small"
# Respuestas con voz: "local" (Piper en el equipo) o "no" (desactivadas).
SPEECH_ENGINES = ("local", "no")
DEFAULT_PIPER_VOICE = "es_MX-ald-medium"


class ConfigError(Exception):
    """La configuración es inválida o está incompleta."""


@dataclass(frozen=True)
class GoogleSettings:
    credentials_file: Path
    token_file: Path
    calendar_id: str


@dataclass(frozen=True)
class SummarySettings:
    """Resumen diario. Por Gmail, `recipient` vacío significa que está desactivado."""

    channel: str  # "gmail" o "telegram"
    recipient: str
    send_time: time
    db_path: Path

    @property
    def enabled(self) -> bool:
        return self.channel == "telegram" or bool(self.recipient)

    @property
    def uses_gmail(self) -> bool:
        return self.channel == "gmail" and bool(self.recipient)


@dataclass(frozen=True)
class TelegramSettings:
    bot_token: str
    owner_id: str | None  # ID numérico de la cuenta de Telegram del usuario


@dataclass(frozen=True)
class VoiceSettings:
    """Notas de voz. `engine` dice quién transcribe; hoy solo "local" (o "no" para desactivarlas)."""

    engine: str
    model: str  # modelo de Whisper: tiny, base, small, medium, large-v3-turbo…
    models_dir: Path  # carpeta donde `preparar-voz` descarga los modelos

    @property
    def enabled(self) -> bool:
        return self.engine != "no"


@dataclass(frozen=True)
class SpeechSettings:
    """Respuestas con voz. `engine` dice quién genera la voz; hoy solo "local" (o "no")."""

    engine: str
    voice: str  # voz de Piper: <idioma>-<nombre>-<calidad>, por ejemplo es_MX-ald-medium
    voices_dir: Path  # carpeta donde `preparar-voz` descarga las voces

    @property
    def enabled(self) -> bool:
        return self.engine != "no"


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    timezone: tzinfo
    calendar_source: str
    google: GoogleSettings
    summary: SummarySettings
    voice: VoiceSettings
    speech: SpeechSettings


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
        voice=load_voice_settings(env),
        speech=load_speech_settings(env),
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
    channel = (_get(env, "JARVIS_RESUMEN_CANAL") or "gmail").lower()
    if channel not in SUMMARY_CHANNELS:
        raise ConfigError(
            f"JARVIS_RESUMEN_CANAL='{channel}' no es válido. Opciones: {', '.join(SUMMARY_CHANNELS)}."
        )
    recipient = _get(env, "JARVIS_RESUMEN_DESTINATARIO")
    if recipient and ("@" not in recipient or " " in recipient):
        raise ConfigError(f"JARVIS_RESUMEN_DESTINATARIO='{recipient}' no parece un correo válido.")
    return SummarySettings(
        channel=channel,
        recipient=recipient,
        send_time=_load_time(env, "JARVIS_RESUMEN_HORA", DEFAULT_SUMMARY_TIME),
        db_path=_path(env, "JARVIS_DB_PATH", DEFAULT_CONFIG_DIR / "jarvis.db"),
    )


def load_voice_settings(env: Mapping[str, str]) -> VoiceSettings:
    engine = (_get(env, "JARVIS_TRANSCRIPCION") or "local").lower()
    if engine not in TRANSCRIPTION_ENGINES:
        raise ConfigError(
            f"JARVIS_TRANSCRIPCION='{engine}' no es válido. Opciones: {', '.join(TRANSCRIPTION_ENGINES)}."
        )
    model = (_get(env, "JARVIS_WHISPER_MODELO") or DEFAULT_WHISPER_MODEL).lower()
    # El nombre se usa como carpeta: solo letras, números, puntos y guiones.
    if not re.fullmatch(r"[a-z0-9][a-z0-9.\-]*", model):
        raise ConfigError(
            f"JARVIS_WHISPER_MODELO='{model}' no es válido. Ejemplos: tiny, base, small, medium."
        )
    return VoiceSettings(engine=engine, model=model, models_dir=DEFAULT_CONFIG_DIR / "voz")


def load_speech_settings(env: Mapping[str, str]) -> SpeechSettings:
    engine = (_get(env, "JARVIS_RESPUESTA_VOZ") or "local").lower()
    if engine not in SPEECH_ENGINES:
        raise ConfigError(
            f"JARVIS_RESPUESTA_VOZ='{engine}' no es válido. Opciones: {', '.join(SPEECH_ENGINES)}."
        )
    voice = _get(env, "JARVIS_PIPER_VOZ") or DEFAULT_PIPER_VOICE
    # Formato de Piper; también se usa como nombre de archivo.
    if not re.fullmatch(r"[a-z]{2,3}_[A-Z]{2}-[A-Za-z0-9_]+-[a-z_]+", voice):
        raise ConfigError(
            f"JARVIS_PIPER_VOZ='{voice}' no es válido. Usa el formato <idioma>-<nombre>-<calidad>, "
            f"por ejemplo {DEFAULT_PIPER_VOICE}."
        )
    return SpeechSettings(engine=engine, voice=voice, voices_dir=DEFAULT_CONFIG_DIR / "voz" / "piper")


def load_telegram_settings(env: Mapping[str, str], require_owner: bool = True) -> TelegramSettings:
    """Configuración del bot de Telegram.

    `require_owner=False` sirve para `telegram-vincular`, que es justo el paso que averigua el ID.
    """
    token = _get(env, "TELEGRAM_BOT_TOKEN")
    if not token:
        raise ConfigError("Falta TELEGRAM_BOT_TOKEN. Crea el bot con @BotFather (ver README).")
    if ":" not in token or " " in token:
        raise ConfigError("TELEGRAM_BOT_TOKEN no parece un token de bot válido (formato 123456:ABC…).")

    owner_id = _get(env, "TELEGRAM_OWNER_ID") or None
    if owner_id is not None and not owner_id.isdigit():
        raise ConfigError(f"TELEGRAM_OWNER_ID='{owner_id}' debe ser un número.")
    if owner_id is None and require_owner:
        raise ConfigError(
            "Falta TELEGRAM_OWNER_ID. Ejecuta `uv run jarvis telegram-vincular` para obtener tu ID."
        )
    return TelegramSettings(bot_token=token, owner_id=owner_id)


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
