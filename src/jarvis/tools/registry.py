"""Registro central de tools: nombre -> definición (schema + función)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from anthropic.types import ToolParam

# Recibe el texto a mostrar al usuario y devuelve True si aprueba la acción.
Confirmer = Callable[[str], bool]

CANCELLED_MESSAGE = "El usuario canceló la acción. No se ejecutó nada."


@dataclass(frozen=True)
class Tool:
    """Una tool disponible para el modelo.

    Si `confirmation_prompt` está definido, la tool tiene efectos externos y el
    registro pide confirmación al usuario antes de ejecutarla.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    func: Callable[..., str]
    confirmation_prompt: Callable[[dict[str, Any]], str] | None = None

    @property
    def requires_confirmation(self) -> bool:
        return self.confirmation_prompt is not None


@dataclass(frozen=True)
class ToolResult:
    content: str
    is_error: bool = False


def deny_all(_prompt: str) -> bool:
    """Confirmador por defecto: rechaza toda acción con efectos externos."""
    return False


class ToolRegistry:
    def __init__(self, confirm: Confirmer = deny_all) -> None:
        self._tools: dict[str, Tool] = {}
        self._confirm = confirm

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Ya existe una tool registrada con el nombre '{tool.name}'.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[ToolParam]:
        """Definiciones de las tools en el formato que espera la API."""
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in self._tools.values()
        ]

    def execute(self, name: str, tool_input: dict[str, Any]) -> ToolResult:
        """Ejecuta una tool. Nunca lanza excepciones: los fallos vuelven como `is_error`."""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(f"La tool '{name}' no existe.", is_error=True)

        problem = _validate_input(tool.input_schema, tool_input)
        if problem:
            return ToolResult(f"Entrada inválida para '{name}': {problem}", is_error=True)

        if tool.confirmation_prompt is not None:
            if not self._confirm(tool.confirmation_prompt(tool_input)):
                return ToolResult(CANCELLED_MESSAGE)

        try:
            return ToolResult(tool.func(**tool_input))
        except Exception as exc:  # noqa: BLE001 - cualquier fallo se reporta al modelo
            return ToolResult(f"Error al ejecutar '{name}': {exc}", is_error=True)


def _validate_input(schema: dict[str, Any], tool_input: dict[str, Any]) -> str | None:
    """Validación mínima: campos requeridos presentes y sin campos desconocidos."""
    if not isinstance(tool_input, dict):
        return "se esperaba un objeto JSON."
    properties = schema.get("properties", {})
    missing = [field for field in schema.get("required", []) if field not in tool_input]
    if missing:
        return f"faltan campos requeridos: {', '.join(missing)}."
    unknown = [field for field in tool_input if field not in properties]
    if unknown:
        return f"campos desconocidos: {', '.join(unknown)}."
    return None
