"""Dobles del cliente de Anthropic compartidos por los tests (sin llamadas reales a la API)."""

from typing import Any

from anthropic.types import Message, TextBlock, ToolUseBlock, Usage


class FakeMessages:
    """Sustituye a `client.messages`: devuelve respuestas guionizadas y registra las llamadas.

    Si una respuesta es una excepción, se lanza en lugar de devolverla.
    """

    def __init__(self, responses: list[Message | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Message:
        # Copia superficial de `messages` porque el agente sigue modificando el historial.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, responses: list[Message | Exception]) -> None:
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
