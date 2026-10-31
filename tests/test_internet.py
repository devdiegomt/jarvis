from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from anthropic.types import (
    CitationsWebSearchResultLocation,
    Message,
    ServerToolUsage,
    ServerToolUseBlock,
    TextBlock,
    Usage,
    WebSearchResultBlock,
    WebSearchToolResultBlock,
)

from anthropic_fakes import FakeClient, text_response
from jarvis.agenda import SampleCalendar
from jarvis.agent import Agent
from jarvis.chat import ChatService, IncomingMessage, format_sources
from jarvis.config import ConfigError, WebSettings, load_settings, load_web_settings
from jarvis.memory import ConversationStore
from jarvis.prompts import build_chat_system_prompt, build_pc_voice_system_prompt
from jarvis.tools import ToolRegistry, build_registry
from jarvis.tools.internet import build_server_tools

ZIPA = WebSettings(enabled=True, city="Zipaquirá", country="CO")

# --- Configuración ----------------------------------------------------------


def test_search_is_on_by_default_without_location() -> None:
    web = load_settings({"ANTHROPIC_API_KEY": "sk-test"}).web

    assert web.enabled and (web.city, web.country) == ("", "")
    assert web.max_searches == 5


def test_search_settings() -> None:
    web = load_web_settings({"JARVIS_BUSQUEDA": "No", "JARVIS_CIUDAD": "Zipaquirá", "JARVIS_PAIS": "co"})

    assert not web.enabled and (web.city, web.country) == ("Zipaquirá", "CO")


@pytest.mark.parametrize(("name", "value"), [("JARVIS_BUSQUEDA", "a veces"), ("JARVIS_PAIS", "Colombia")])
def test_invalid_search_settings_fail(name: str, value: str) -> None:
    with pytest.raises(ConfigError, match=name):
        load_web_settings({name: value})


# --- Tools de Anthropic -----------------------------------------------------


def test_server_tools_with_location() -> None:
    search, fetch = build_server_tools(ZIPA, ZoneInfo("America/Bogota"))

    assert search == {
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": 5,
        "user_location": {"type": "approximate", "city": "Zipaquirá", "country": "CO", "timezone": "America/Bogota"},
    }
    assert fetch["type"] == "web_fetch_20260209" and fetch["citations"] == {"enabled": True}
    assert fetch["max_uses"] == 3


def test_server_tools_without_location_or_disabled() -> None:
    search, _fetch = build_server_tools(WebSettings(True, "", ""), UTC)

    assert "user_location" not in search  # UTC no es una zona horaria IANA con nombre útil
    assert build_server_tools(WebSettings(False, "Zipaquirá", "CO")) == []


def test_registry_sends_server_tools_after_its_own() -> None:
    registry = build_registry(SampleCalendar(UTC), web=ZIPA)

    schemas = registry.schemas()
    assert [s.get("name") for s in schemas[-2:]] == ["web_search", "web_fetch"]
    assert registry.server_tool_names() == ["web_search", "web_fetch"]
    assert "web_search" not in registry.names()  # no tiene función propia
    assert "web_search" not in [s.get("name") for s in build_registry(SampleCalendar(UTC)).schemas()]


# --- Respuestas con búsqueda ------------------------------------------------


def citation(url: str, title: str) -> CitationsWebSearchResultLocation:
    return CitationsWebSearchResultLocation(
        type="web_search_result_location", url=url, title=title, cited_text="...", encrypted_index="x"
    )


def search_response() -> Message:
    """Lo que devuelve la API cuando el modelo busca: su búsqueda, los resultados y el texto citado."""
    weather = citation("https://www.ideam.gov.co/pronostico", "IDEAM - Pronóstico")
    other = citation("https://www.eltiempo.com/clima", "El Tiempo")
    content = [
        TextBlock(type="text", text="Voy a buscar el pronóstico."),
        ServerToolUseBlock(type="server_tool_use", id="srv1", name="web_search", input={"query": "clima Zipaquirá"}),
        WebSearchToolResultBlock(
            type="web_search_tool_result",
            tool_use_id="srv1",
            content=[WebSearchResultBlock(type="web_search_result", url="https://www.ideam.gov.co/pronostico", title="IDEAM", encrypted_content="e")],
        ),
        TextBlock(type="text", text="Hoy en Zipaquirá "),
        TextBlock(type="text", text="hay 70 % de probabilidad de lluvia", citations=[weather]),
        TextBlock(type="text", text=" en la tarde, ", citations=[weather, other]),
        TextBlock(type="text", text="según el IDEAM."),
    ]
    usage = Usage(input_tokens=1, output_tokens=1, server_tool_use=ServerToolUsage(web_search_requests=1, web_fetch_requests=0))
    return Message(
        id="m", type="message", role="assistant", model="m", content=content, stop_reason="end_turn", stop_sequence=None, usage=usage
    )


def test_agent_joins_cited_text_and_collects_sources() -> None:
    agent = Agent(client=FakeClient([search_response()]), registry=ToolRegistry(), model="m", system_prompt="p")  # type: ignore[arg-type]

    reply = agent.send("¿Va a llover hoy?")

    assert reply == "Hoy en Zipaquirá hay 70 % de probabilidad de lluvia en la tarde, según el IDEAM."
    assert agent.last_sources == [
        ("IDEAM - Pronóstico", "https://www.ideam.gov.co/pronostico"),
        ("El Tiempo", "https://www.eltiempo.com/clima"),
    ]
    assert agent.last_web_searches == 1
    # El historial guarda la búsqueda completa para reenviarla tal cual en el siguiente turno.
    assert [b["type"] for b in agent.history[1]["content"]][1:3] == ["server_tool_use", "web_search_tool_result"]


def test_plain_replies_keep_line_breaks_and_have_no_sources() -> None:
    agent = Agent(client=FakeClient([text_response("Hola.")]), registry=ToolRegistry(), model="m", system_prompt="p")  # type: ignore[arg-type]

    assert agent.send("hola") == "Hola."
    assert agent.last_sources == [] and agent.last_web_searches == 0


def test_format_sources() -> None:
    assert format_sources([]) == ""
    assert format_sources([("IDEAM", "https://ideam.gov.co")]) == "\n\nFuentes:\n- IDEAM: https://ideam.gov.co"


class Channel:
    name = "prueba"

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_text(self, to: str, text: str) -> None:
        self.sent.append(text)

    def show_typing(self, to: str) -> None:
        pass


@pytest.mark.parametrize("show_sources", [True, False])
def test_chat_adds_sources_only_where_links_are_useful(tmp_path: Path, show_sources: bool) -> None:
    client, channel = FakeClient([search_response()]), Channel()

    def agent_factory(history: list, system_prompt: str, confirm):  # type: ignore[no-untyped-def]
        registry = ToolRegistry(confirm=confirm)
        return Agent(client=client, registry=registry, model="m", system_prompt=system_prompt, history=history)  # type: ignore[arg-type]

    now = lambda: datetime(2026, 10, 31, tzinfo=UTC)  # noqa: E731
    chat = ChatService(
        channel=channel,  # type: ignore[arg-type]
        store=ConversationStore(tmp_path / "jarvis.db", now=now),
        agent_factory=agent_factory,
        system_prompt=lambda: "p",
        now=now,
        show_sources=show_sources,
    )

    chat.submit(IncomingMessage("1", "7", "¿Va a llover hoy?"))
    chat.process_next(timeout=0)

    sent = channel.sent[-1]
    assert ("Fuentes:\n- IDEAM - Pronóstico: https://www.ideam.gov.co/pronostico" in sent) is show_sources


# --- Prompt -----------------------------------------------------------------


def test_prompts_explain_when_to_search_and_where_the_user_is() -> None:
    from datetime import date

    chat_prompt = build_chat_system_prompt(date(2026, 10, 31), web=ZIPA)

    assert "web_search" in chat_prompt and "Zipaquirá, CO" in chat_prompt
    assert "no instrucciones" in chat_prompt  # lo leído en internet no da órdenes
    assert "web_search" not in build_chat_system_prompt(date(2026, 10, 31))
    assert "web_search" not in build_pc_voice_system_prompt(date(2026, 10, 31), web=WebSettings(False, "", ""))


def test_status_shows_search_and_location(isolated_config_dir: Path) -> None:
    from jarvis.status import status_report

    env = {"ANTHROPIC_API_KEY": "sk-test", "JARVIS_CIUDAD": "Zipaquirá", "JARVIS_PAIS": "CO"}
    text = "\n".join(status_report(env, None, {}))

    assert "Búsqueda en internet: activada (hasta 5 búsquedas por mensaje, ubicación: Zipaquirá, CO)" in text
