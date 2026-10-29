from typing import Any

import pytest

from anthropic_fakes import FakeClient, text_response
from jarvis import summary_cli
from jarvis.config import load_settings


def run_dry(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    settings = load_settings({"ANTHROPIC_API_KEY": "sk-test", "JARVIS_TIMEZONE": "America/Bogota", **env})
    monkeypatch.setattr(summary_cli, "load_settings", lambda: settings)
    monkeypatch.setattr(summary_cli.anthropic, "Anthropic", lambda **_kw: FakeClient([text_response("Día tranquilo.")]))
    summary_cli.run_summary(dry_run=True, force=False, scheduled=False)


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"JARVIS_RESUMEN_CANAL": "telegram"}, "Canal configurado: Telegram."),
        ({"JARVIS_RESUMEN_DESTINATARIO": "yo@example.com"}, "Canal configurado: Gmail a yo@example.com."),
        ({}, "Canal configurado: ninguno."),
    ],
)
def test_dry_run_shows_the_configured_channel(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], env: dict[str, Any], expected: str
) -> None:
    run_dry(monkeypatch, env)

    output = capsys.readouterr().out
    assert "Modo prueba: no se envió nada." in output
    assert expected in output


def test_dry_run_without_channel_explains_how_to_configure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dry(monkeypatch, {})

    assert "JARVIS_RESUMEN_CANAL=telegram" in capsys.readouterr().out
