from typing import Any

from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from jarvis.agent import ITERATION_LIMIT_MESSAGE, REFUSAL_MESSAGE, Agent
from jarvis.tools import Tool, ToolRegistry

ECHO_SCHEMA = {
    "type": "object",
    "properties": {"texto": {"type": "string"}},
    "required": ["texto"],
}


class FakeMessages:
    """Sustituye a `client.messages`: devuelve respuestas guionizadas y registra las llamadas."""

    def __init__(self, responses: list[Message]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Message:
        # Copia superficial de `messages` porque el agente sigue modificando el historial.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[Message]) -> None:
        self.messages = FakeMessages(responses)


def text_response(text: str, stop_reason: str = "end_turn") -> Message:
    return _message([TextBlock(type="text", text=text)], stop_reason)


def tool_response(*calls: tuple[str, str, dict[str, Any]]) -> Message:
    blocks = [ToolUseBlock(type="tool_use", id=id_, name=name, input=inp) for id_, name, inp in calls]
    return _message(blocks, "tool_use")


def _message(content: list[Any], stop_reason: str) -> Message:
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="test-model",
        content=content,
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def make_agent(responses: list[Message], registry: ToolRegistry | None = None, **kwargs: Any) -> tuple[Agent, FakeClient]:
    if registry is None:
        registry = ToolRegistry()
        registry.register(Tool(name="echo", description="Repite.", input_schema=ECHO_SCHEMA, func=lambda texto: texto))
    client = FakeClient(responses)
    agent = Agent(client=client, registry=registry, model="test-model", system_prompt="Eres JARVIS.", **kwargs)  # type: ignore[arg-type]
    return agent, client


def test_direct_answer_without_tools() -> None:
    agent, client = make_agent([text_response("¡Hola!")])

    assert agent.send("hola") == "¡Hola!"
    assert len(client.messages.calls) == 1
    call = client.messages.calls[0]
    assert call["model"] == "test-model"
    assert call["system"] == "Eres JARVIS."
    assert [t["name"] for t in call["tools"]] == ["echo"]


def test_tool_use_round_then_final_answer() -> None:
    agent, client = make_agent(
        [tool_response(("toolu_1", "echo", {"texto": "ping"})), text_response("Listo: ping")]
    )

    assert agent.send("haz eco") == "Listo: ping"
    assert len(client.messages.calls) == 2

    tool_result_message = client.messages.calls[1]["messages"][-1]
    assert tool_result_message["role"] == "user"
    assert tool_result_message["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ping", "is_error": False}
    ]


def test_parallel_tool_calls_return_results_in_single_message() -> None:
    agent, client = make_agent(
        [
            tool_response(("t1", "echo", {"texto": "a"}), ("t2", "echo", {"texto": "b"})),
            text_response("ok"),
        ]
    )

    agent.send("dos ecos")

    results = client.messages.calls[1]["messages"][-1]["content"]
    assert [(r["tool_use_id"], r["content"]) for r in results] == [("t1", "a"), ("t2", "b")]


def test_tool_error_is_sent_back_to_model() -> None:
    agent, client = make_agent([tool_response(("t1", "no_existe", {})), text_response("Esa tool no existe.")])

    assert agent.send("usa algo raro") == "Esa tool no existe."
    result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert result["tool_use_id"] == "t1"


def test_iteration_limit_stops_the_loop() -> None:
    endless = [tool_response((f"t{i}", "echo", {"texto": "otra vez"})) for i in range(20)]
    agent, client = make_agent(endless, max_iterations=10)

    assert agent.send("bucle") == ITERATION_LIMIT_MESSAGE
    assert len(client.messages.calls) == 10


def test_history_is_kept_between_messages() -> None:
    agent, client = make_agent([text_response("Hola, Diego."), text_response("Te llamas Diego.")])

    agent.send("Me llamo Diego")
    agent.send("¿Cómo me llamo?")

    second_call = client.messages.calls[1]["messages"]
    assert [m["role"] for m in second_call] == ["user", "assistant", "user"]
    assert second_call[0]["content"][0]["text"] == "Me llamo Diego"
    assert second_call[2]["content"][0]["text"] == "¿Cómo me llamo?"


def test_roles_alternate_after_hitting_iteration_limit() -> None:
    responses = [tool_response(("t1", "echo", {"texto": "x"})), text_response("De acuerdo.")]
    agent, client = make_agent(responses, max_iterations=1)

    assert agent.send("primero") == ITERATION_LIMIT_MESSAGE
    agent.send("segundo")

    messages = client.messages.calls[1]["messages"]
    roles = [m["role"] for m in messages]
    assert roles == ["user", "assistant", "user"]
    assert messages[-1]["content"][-1] == {"type": "text", "text": "segundo"}


def test_refusal_returns_friendly_message() -> None:
    agent, _ = make_agent([text_response("", stop_reason="refusal")])

    assert agent.send("algo prohibido") == REFUSAL_MESSAGE
