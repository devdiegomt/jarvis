"""Loop del agente: conversa con Claude y ejecuta las tools que pida."""

from collections.abc import Iterable
from typing import Any

from anthropic import Anthropic
from anthropic.types import ContentBlock, MessageParam, ToolResultBlockParam

from jarvis.tools import ToolRegistry

MAX_ITERATIONS = 10
MAX_TOKENS = 16000
MAX_SOURCES = 3

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
        history: list[MessageParam] | None = None,
        effort: str | None = None,
    ) -> None:
        """`effort`: cuánto razona el modelo (low… max); None usa el valor por defecto del modelo."""
        self._client = client
        self._effort = effort
        self._registry = registry
        self._model = model
        self._system_prompt = system_prompt
        self._max_iterations = max_iterations
        # El historial es JSON plano (dicts), así se puede guardar y recuperar tal cual.
        self.history: list[MessageParam] = history if history is not None else []
        # Del último `send`: páginas citadas (título, URL) y búsquedas en internet hechas.
        self.last_sources: list[tuple[str, str]] = []
        self.last_web_searches = 0

    def send(self, user_message: str) -> str:
        """Procesa un mensaje del usuario y devuelve la respuesta final de JARVIS."""
        self._append_user_content([{"type": "text", "text": user_message}])
        self.last_sources, self.last_web_searches = [], 0

        options: dict[str, Any] = {"output_config": {"effort": self._effort}} if self._effort else {}
        for _ in range(self._max_iterations):
            response = self._client.messages.create(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=self._system_prompt,
                tools=self._registry.schemas(),
                messages=self.history,
                **options,
            )
            # Se guarda el contenido completo (incluidos bloques de thinking y tool_use).
            self.history.append(
                {"role": "assistant", "content": [_block_to_param(b) for b in response.content]}
            )
            self._note_web_use(response)

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

    def _note_web_use(self, response: Any) -> None:
        """Anota las fuentes citadas y cuántas búsquedas hizo el modelo (las búsquedas se pagan)."""
        server_use = getattr(getattr(response, "usage", None), "server_tool_use", None)
        self.last_web_searches += int(getattr(server_use, "web_search_requests", 0) or 0)
        for block in response.content:
            for citation in getattr(block, "citations", None) or []:
                url = getattr(citation, "url", None)
                if url and all(url != known for _, known in self.last_sources):
                    self.last_sources.append((getattr(citation, "title", None) or url, url))
        del self.last_sources[MAX_SOURCES:]

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


def _block_to_param(block: ContentBlock) -> dict[str, Any]:
    """Convierte un bloque de la respuesta en un dict reenviable a la API sin cambios."""
    return block.model_dump(mode="json", exclude_none=True)


def _is_server_tool_block(block_type: str) -> bool:
    return block_type == "server_tool_use" or block_type.endswith("_tool_result")


def _extract_text(content: Iterable[ContentBlock]) -> str:
    """Texto final de la respuesta.

    Tras una búsqueda en internet, el modelo responde en varios trozos de texto (uno por cita) que
    forman frases seguidas: se unen sin separador, y se omite lo que dijo antes de buscar.
    """
    blocks = list(content)
    server_blocks = [i for i, block in enumerate(blocks) if _is_server_tool_block(block.type)]
    last_server_block = server_blocks[-1] if server_blocks else None
    if last_server_block is None:
        return "\n".join(block.text for block in blocks if block.type == "text").strip()
    return "".join(block.text for block in blocks[last_server_block + 1 :] if block.type == "text").strip()
