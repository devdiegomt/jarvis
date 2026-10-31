from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from anthropic.types import Message, ServerToolUsage, TextBlock, ToolUseBlock, Usage as ApiUsage

from anthropic_fakes import FakeClient
from jarvis.agent import Agent
from jarvis.agenda import SampleCalendar
from jarvis.chat import ChatService, IncomingMessage
from jarvis.memory import ConversationStore
from jarvis.summary import send_daily_summary
from jarvis.tools import ToolRegistry, build_registry
from jarvis.usage import (
    Usage,
    UsageLog,
    describe_usage,
    estimate_cost,
    format_usd,
    spending_text,
    usage_from_response,
)

TZ = ZoneInfo("America/Bogota")
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=TZ)
MODEL = "claude-sonnet-5-5"


def message(content: list[Any], stop_reason: str, **usage: Any) -> Message:
    return Message(
        id="m",
        type="message",
        role="assistant",
        model=MODEL,
        content=content,
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=ApiUsage(**{"input_tokens": 0, "output_tokens": 0, **usage}),
    )


# --- Costo ----------------------------------------------------------------------


def test_cost_uses_public_prices() -> None:
    usage = Usage(input_tokens=1_000_000, cache_write_tokens=0, cache_read_tokens=1_000_000, output_tokens=100_000)

    assert estimate_cost(MODEL, usage) == pytest.approx(2.00 + 0.20 + 1.00)
    assert estimate_cost(MODEL, Usage(web_searches=3)) == pytest.approx(0.03)
    assert estimate_cost("modelo-desconocido", usage) is None


def test_usage_is_read_tolerantly_from_the_api() -> None:
    response = message(
        [],
        "end_turn",
        input_tokens=120,
        cache_creation_input_tokens=3000,
        cache_read_input_tokens=0,
        output_tokens=80,
        server_tool_use=ServerToolUsage(web_search_requests=2, web_fetch_requests=0),
    )

    assert usage_from_response(response) == Usage(120, 3000, 0, 80, 2)
    assert usage_from_response(object()) == Usage()


def test_log_line_has_numbers_only() -> None:
    line = describe_usage(MODEL, Usage(200, 0, 4000, 150, 1))

    assert line == "4.200 tokens de entrada (4.000 de caché), 150 de salida, 1 búsqueda(s) ≈ $0,0127"
    assert format_usd(1.234) == "$1,23"


# --- Caché y medición en el agente ----------------------------------------------


def test_agent_asks_for_caching_and_adds_up_every_call() -> None:
    client = FakeClient(
        [
            message([ToolUseBlock(type="tool_use", id="t1", name="get_reuniones", input={})], "tool_use",
                    input_tokens=50, cache_creation_input_tokens=4000, output_tokens=30),
            message([TextBlock(type="text", text="Tienes 3 reuniones.")], "end_turn",
                    input_tokens=60, cache_read_input_tokens=4030, output_tokens=20),
        ]
    )
    agent = Agent(client=client, registry=build_registry(SampleCalendar(TZ)), model=MODEL, system_prompt="p")  # type: ignore[arg-type]

    agent.send("¿Qué tengo hoy?")

    assert all(call["cache_control"] == {"type": "ephemeral"} for call in client.messages.calls)
    assert client.messages.calls[0]["system"] == "p"  # el system prompt no cambia por la caché
    assert agent.last_usage == Usage(110, 4000, 4030, 50, 0)
    assert agent.model == MODEL


# --- Registro y /gasto ------------------------------------------------------------


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


def test_spending_by_period(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 10, 30, 9, 0, tzinfo=TZ))  # viernes de la semana anterior
    log = UsageLog(tmp_path / "jarvis.db", now=clock)
    log.record("telegram", MODEL, Usage(1_000_000, 0, 0, 0))  # $2,00 el 30 de octubre
    clock.moment = NOW
    log.record("telegram", MODEL, Usage(0, 0, 900_000, 10_000, 1))  # $0,18 + $0,10 + $0,01 hoy
    log.record("resumen", MODEL, Usage(100_000, 0, 0, 0))  # $0,20 hoy

    text = spending_text(log, NOW, TZ)

    assert "- Hoy: $0,49 (2 respuestas, 1 búsqueda(s))" in text
    assert "- Últimos 7 días: $2,49 (3 respuestas, 1 búsqueda(s))" in text
    assert "- Este mes: $0,49 (2 respuestas, 1 búsqueda(s))" in text  # noviembre
    assert "90% salió de la caché" in text


def test_spending_without_data_and_with_unknown_models(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "jarvis.db", now=lambda: NOW)
    assert "- Hoy: nada" in spending_text(log, NOW, TZ)
    assert not (tmp_path / "jarvis.db").exists()  # consultar no crea la base de datos

    log.record("consola", "modelo-nuevo", Usage(1000, 0, 0, 500))
    assert "1.500 tokens (1 respuesta; sin precio para el modelo)" in spending_text(log, NOW, TZ)


def test_old_usage_is_purged(tmp_path: Path) -> None:
    clock = Clock(NOW - timedelta(days=500))
    log = UsageLog(tmp_path / "jarvis.db", now=clock)
    log.record("telegram", MODEL, Usage(10, 0, 0, 10))
    clock.moment = NOW

    assert log.purge_old() == 1


class Channel:
    name = "telegram"

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_text(self, to: str, text: str) -> None:
        self.sent.append(text)

    def show_typing(self, to: str) -> None:
        pass


def chat_with(tmp_path: Path, client: FakeClient, **kwargs: Any) -> tuple[ChatService, Channel, UsageLog]:
    channel, log = Channel(), UsageLog(tmp_path / "jarvis.db", now=lambda: NOW)

    def agent_factory(history: list, system_prompt: str, confirm):  # type: ignore[no-untyped-def]
        return Agent(client=client, registry=ToolRegistry(confirm=confirm), model=MODEL, system_prompt=system_prompt, history=history)  # type: ignore[arg-type]

    chat = ChatService(
        channel=channel,  # type: ignore[arg-type]
        store=ConversationStore(tmp_path / "jarvis.db", now=lambda: NOW),
        agent_factory=agent_factory,
        system_prompt=lambda: "p",
        now=lambda: NOW,
        usage_log=log,
        **kwargs,
    )
    return chat, channel, log


def test_chat_records_each_answer_without_content(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    client = FakeClient([message([TextBlock(type="text", text="Hola Diego")], "end_turn", input_tokens=900, output_tokens=40)])
    chat, _, log = chat_with(tmp_path, client)

    with caplog.at_level("INFO", logger="jarvis.chat"):
        chat.submit(IncomingMessage("1", "7", "hola, soy Diego"))
        chat.process_next(timeout=0)

    assert log.since(NOW - timedelta(hours=1)).usage == Usage(900, 0, 0, 40)
    assert "Claude: 900 tokens de entrada (0 de caché), 40 de salida ≈ $0,0022" in caplog.text
    assert "Diego" not in caplog.text


def test_api_errors_after_some_calls_still_count(tmp_path: Path) -> None:
    import anthropic
    import httpx2 as httpx

    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    first = message([ToolUseBlock(type="tool_use", id="t1", name="nada", input={})], "tool_use", input_tokens=500, output_tokens=10)
    chat, channel, log = chat_with(tmp_path, FakeClient([first, error]))

    chat.submit(IncomingMessage("1", "7", "hola"))
    chat.process_next(timeout=0)

    assert "problema al consultar la IA" in channel.sent[-1]
    assert log.since(NOW - timedelta(hours=1)).requests == 1


def test_quick_commands_never_call_claude(tmp_path: Path) -> None:
    client = FakeClient([])
    chat, channel, _ = chat_with(tmp_path, client, quick_commands={"/gasto": lambda: "💸 nada"})

    chat.submit(IncomingMessage("1", "7", "/gasto"))
    chat.process_next(timeout=0)

    assert channel.sent == ["💸 nada"] and client.messages.calls == []


# --- Resumen y estado ---------------------------------------------------------------


def test_summary_comment_is_counted(tmp_path: Path) -> None:
    client = FakeClient([message([TextBlock(type="text", text="Día tranquilo.")], "end_turn", input_tokens=700, output_tokens=60)])
    log = UsageLog(tmp_path / "jarvis.db", now=lambda: NOW)
    sent: list[str] = []
    notifier = type("N", (), {"send": lambda _s, subject, body: sent.append(body)})()

    send_daily_summary(
        day=NOW.date(),
        calendar=SampleCalendar(TZ),
        notifier=notifier,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        model=MODEL,
        log=None,
        now=lambda: NOW,
        usage_log=log,
    )

    assert log.since(NOW - timedelta(hours=1)).usage == Usage(700, 0, 0, 60)


def test_status_shows_the_spending(isolated_config_dir: Path) -> None:
    from jarvis.status import status_report

    env = {"ANTHROPIC_API_KEY": "sk-test"}
    assert "Gasto en Claude: nada todavía" in "\n".join(status_report(env, None, {}))

    db = isolated_config_dir / "jarvis.db"
    UsageLog(db, now=lambda: datetime.now(UTC)).record("telegram", MODEL, Usage(1_000_000, 0, 0, 0))
    assert "- Hoy: $2,00 (1 respuesta)" in "\n".join(status_report(env, None, {}))
