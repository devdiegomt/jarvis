"""Loop del agente: conversa con Claude y ejecuta las tools que pida."""

from collections.abc import Iterable
from typing import Any

from anthropic import Anthropic
from anthropic.types import ContentBlock, MessageParam, ToolResultBlockParam

from jarvis.tools import ToolRegistry

MAX_ITERATIONS = 10
MAX_TOKENS = 16000

ITERATION_LIMIT_MESSAGE = (
    "Me detuve porque la tarea requería demasiados pasos. "
    "¿Puedes darme más detalles o dividirla en partes más pequeñas?"
)
REFUSAL_MESSAGE = "Lo siento, no puedo ayudar con esa petición."
TRUNCATED_NOTE = "(Respuesta cortada por longitud.)"


class Agent:
    """Mantiene el historial de la sesión y ejecuta el loop de tool use."""

    def __init__(
        self,
        client: Anthropic,
        registry: ToolRegistry,
        model: str,
        system_prompt: str,
        max_iterations: int = MAX_ITERATIONS,
    ) -> None:
        self._client = client
        self._registry = registry
        self._model = model
        self._system_prompt = system_prompt
        self._max_iterations = max_iterations
        self.history: list[MessageParam] = []

    def send(self, user_message: str) -> str:
        """Procesa un mensaje del usuario y devuelve la respuesta final de JARVIS."""
        self._append_user_content([{"type": "text", "text": user_message}])

        for _ in range(self._max_iterations):
            response = self._client.messages.create(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=self._system_prompt,
                tools=self._registry.schemas(),
                messages=self.history,
            )
            # Se guarda el contenido completo (incluidos bloques de thinking y tool_use).
            self.history.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                self._append_user_content(self._run_tools(response.content))
                continue
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason == "refusal":
                return REFUSAL_MESSAGE

            text = _extract_text(response.content)
            if response.stop_reason == "max_tokens":
                return f"{text}\n{TRUNCATED_NOTE}".strip()
            return text

        return ITERATION_LIMIT_MESSAGE

    def _run_tools(self, content: Iterable[ContentBlock]) -> list[ToolResultBlockParam]:
        """Ejecuta todas las tools pedidas y devuelve sus resultados en un solo bloque."""
        results: list[ToolResultBlockParam] = []
        for block in content:
            if block.type != "tool_use":
                continue
            result = self._registry.execute(block.name, block.input)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result.content,
                    "is_error": result.is_error,
                }
            )
        return results

    def _append_user_content(self, blocks: list[Any]) -> None:
        """Agrega contenido del usuario manteniendo la alternancia de roles.

        Si el último mensaje ya es del usuario (por ejemplo, resultados de tools tras
        alcanzar el límite de iteraciones, o un error de la API), se une a ese mensaje.
        """
        if self.history and self.history[-1]["role"] == "user":
            previous = self.history[-1]["content"]
            assert isinstance(previous, list)
            previous.extend(blocks)
        else:
            self.history.append({"role": "user", "content": blocks})


def _extract_text(content: Iterable[ContentBlock]) -> str:
    return "\n".join(block.text for block in content if block.type == "text").strip()
