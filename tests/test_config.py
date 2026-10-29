from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from jarvis.agenda import SampleCalendar, build_calendar
from jarvis.agenda.google import GoogleCalendar
from jarvis.config import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_MODEL,
    ConfigError,
    load_settings,
    load_telegram_settings,
)

BASE_ENV = {"ANTHROPIC_API_KEY": "sk-test"}


def test_defaults() -> None:
    settings = load_settings(BASE_ENV)

    assert settings.model == DEFAULT_MODEL
    assert settings.calendar_source == "sample"
    assert settings.google.calendar_id == "primary"
    assert settings.google.credentials_file == DEFAULT_CONFIG_DIR / "credentials.json"
    assert settings.google.token_file == DEFAULT_CONFIG_DIR / "token.json"
    assert settings.timezone is not None  # la del sistema


def test_missing_api_key_fails() -> None:
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        load_settings({})


def test_custom_values() -> None:
    settings = load_settings(
        {
            **BASE_ENV,
            "JARVIS_MODEL": "otro-modelo",
            "JARVIS_TIMEZONE": "America/Bogota",
            "JARVIS_CALENDAR": "Google",
            "GOOGLE_CALENDAR_ID": "trabajo@example.com",
            "GOOGLE_TOKEN_FILE": "~/tokens/jarvis.json",
        }
    )

    assert settings.model == "otro-modelo"
    assert settings.timezone == ZoneInfo("America/Bogota")
    assert settings.calendar_source == "google"
    assert settings.google.calendar_id == "trabajo@example.com"
    assert settings.google.token_file == Path.home() / "tokens" / "jarvis.json"


def test_invalid_timezone_fails() -> None:
    with pytest.raises(ConfigError, match="JARVIS_TIMEZONE"):
        load_settings({**BASE_ENV, "JARVIS_TIMEZONE": "Marte/Olympus"})


def test_invalid_calendar_source_fails() -> None:
    with pytest.raises(ConfigError, match="JARVIS_CALENDAR"):
        load_settings({**BASE_ENV, "JARVIS_CALENDAR": "outlook"})


def test_build_calendar_sample() -> None:
    assert isinstance(build_calendar(load_settings(BASE_ENV)), SampleCalendar)


def test_build_calendar_google_requires_login(tmp_path: Path) -> None:
    settings = load_settings(
        {**BASE_ENV, "JARVIS_CALENDAR": "google", "GOOGLE_TOKEN_FILE": str(tmp_path / "token.json")}
    )

    with pytest.raises(ConfigError, match="google-login"):
        build_calendar(settings)


def test_build_calendar_google_with_token(tmp_path: Path) -> None:
    token_file = tmp_path / "token.json"
    token_file.write_text("{}")
    settings = load_settings({**BASE_ENV, "JARVIS_CALENDAR": "google", "GOOGLE_TOKEN_FILE": str(token_file)})

    assert isinstance(build_calendar(settings), GoogleCalendar)


def test_summary_disabled_by_default() -> None:
    summary = load_settings(BASE_ENV).summary

    assert not summary.enabled
    assert summary.send_time == time(7, 0)
    assert summary.db_path == DEFAULT_CONFIG_DIR / "jarvis.db"


def test_summary_custom_values() -> None:
    summary = load_settings(
        {**BASE_ENV, "JARVIS_RESUMEN_DESTINATARIO": "yo@example.com", "JARVIS_RESUMEN_HORA": "6:45"}
    ).summary

    assert summary.enabled
    assert summary.recipient == "yo@example.com"
    assert summary.send_time == time(6, 45)


@pytest.mark.parametrize(
    ("name", "value"),
    [("JARVIS_RESUMEN_DESTINATARIO", "no-es-un-correo"), ("JARVIS_RESUMEN_HORA", "7 am"), ("JARVIS_RESUMEN_HORA", "25:00")],
)
def test_invalid_summary_settings_fail(name: str, value: str) -> None:
    with pytest.raises(ConfigError, match=name):
        load_settings({**BASE_ENV, name: value})


TELEGRAM_ENV = {"TELEGRAM_BOT_TOKEN": "123456:ABC-def", "TELEGRAM_OWNER_ID": "987654321"}


def test_telegram_settings() -> None:
    telegram = load_telegram_settings(TELEGRAM_ENV)

    assert telegram.bot_token == "123456:ABC-def"
    assert telegram.owner_id == "987654321"


def test_telegram_owner_is_optional_only_for_linking() -> None:
    env = {"TELEGRAM_BOT_TOKEN": "123456:ABC-def"}

    assert load_telegram_settings(env, require_owner=False).owner_id is None
    with pytest.raises(ConfigError, match="telegram-vincular"):
        load_telegram_settings(env)


@pytest.mark.parametrize(
    ("name", "value"),
    [("TELEGRAM_BOT_TOKEN", ""), ("TELEGRAM_BOT_TOKEN", "sin-dos-puntos"), ("TELEGRAM_OWNER_ID", "@usuario")],
)
def test_telegram_invalid_values(name: str, value: str) -> None:
    with pytest.raises(ConfigError, match=name):
        load_telegram_settings({**TELEGRAM_ENV, name: value})


def test_summary_channel() -> None:
    gmail = load_settings({**BASE_ENV, "JARVIS_RESUMEN_DESTINATARIO": "yo@example.com"}).summary
    telegram = load_settings({**BASE_ENV, "JARVIS_RESUMEN_CANAL": "Telegram"}).summary

    assert gmail.channel == "gmail" and gmail.enabled and gmail.uses_gmail
    assert telegram.channel == "telegram" and telegram.enabled and not telegram.uses_gmail


def test_telegram_summary_never_needs_gmail() -> None:
    summary = load_settings(
        {**BASE_ENV, "JARVIS_RESUMEN_CANAL": "telegram", "JARVIS_RESUMEN_DESTINATARIO": "yo@example.com"}
    ).summary

    assert not summary.uses_gmail


def test_invalid_summary_channel() -> None:
    with pytest.raises(ConfigError, match="JARVIS_RESUMEN_CANAL"):
        load_settings({**BASE_ENV, "JARVIS_RESUMEN_CANAL": "whatsapp"})
