import json

import pytest

from jarvis.tools import BUILTIN_TOOLS, Tool, ToolRegistry, build_registry
from jarvis.tools.mensajes import TOOL as ENVIAR_MENSAJE
from jarvis.tools.registry import CANCELLED_MESSAGE
from jarvis.tools.reuniones import get_reuniones

ECHO_SCHEMA = {
    "type": "object",
    "properties": {"texto": {"type": "string"}},
    "required": ["texto"],
}


def make_tool(name: str = "echo", func=lambda texto: texto, **kwargs) -> Tool:
    return Tool(name=name, description="Repite el texto.", input_schema=ECHO_SCHEMA, func=func, **kwargs)


# --- Registro ---------------------------------------------------------------


def test_register_and_list_schemas() -> None:
    registry = ToolRegistry()
    registry.register(make_tool())

    assert registry.names() == ["echo"]
    assert registry.schemas() == [
        {"name": "echo", "description": "Repite el texto.", "input_schema": ECHO_SCHEMA}
    ]


def test_register_duplicate_name_fails() -> None:
    registry = ToolRegistry()
    registry.register(make_tool())

    with pytest.raises(ValueError):
        registry.register(make_tool())


def test_execute_returns_tool_output() -> None:
    registry = ToolRegistry()
    registry.register(make_tool())

    result = registry.execute("echo", {"texto": "hola"})

    assert result.content == "hola"
    assert not result.is_error


def test_execute_unknown_tool_is_error() -> None:
    result = ToolRegistry().execute("no_existe", {})

    assert result.is_error
    assert "no_existe" in result.content


@pytest.mark.parametrize(
    ("tool_input", "expected"),
    [({}, "faltan campos requeridos"), ({"texto": "a", "extra": 1}, "campos desconocidos")],
)
def test_execute_invalid_input_is_error(tool_input: dict, expected: str) -> None:
    registry = ToolRegistry()
    registry.register(make_tool())

    result = registry.execute("echo", tool_input)

    assert result.is_error
    assert expected in result.content


def test_execute_exception_becomes_error_result() -> None:
    def broken(texto: str) -> str:
        raise RuntimeError("se rompió")

    registry = ToolRegistry()
    registry.register(make_tool(func=broken))

    result = registry.execute("echo", {"texto": "x"})

    assert result.is_error
    assert "se rompió" in result.content


# --- Confirmación -----------------------------------------------------------


def test_tool_with_confirmation_runs_when_approved() -> None:
    prompts: list[str] = []
    calls: list[str] = []

    def confirm(prompt: str) -> bool:
        prompts.append(prompt)
        return True

    registry = ToolRegistry(confirm=confirm)
    registry.register(
        make_tool(func=lambda texto: calls.append(texto) or "ok", confirmation_prompt=lambda i: f"¿{i['texto']}?")
    )

    result = registry.execute("echo", {"texto": "enviar"})

    assert prompts == ["¿enviar?"]
    assert calls == ["enviar"]
    assert result.content == "ok"


def test_tool_with_confirmation_does_not_run_when_rejected() -> None:
    calls: list[str] = []
    registry = ToolRegistry(confirm=lambda _prompt: False)
    registry.register(make_tool(func=lambda texto: calls.append(texto) or "ok", confirmation_prompt=lambda i: "?"))

    result = registry.execute("echo", {"texto": "enviar"})

    assert calls == []
    assert result.content == CANCELLED_MESSAGE
    assert not result.is_error


def test_default_registry_denies_actions_with_external_effects() -> None:
    result = build_registry().execute("enviar_mensaje", {"destinatario": "Ana", "texto": "Hola"})

    assert result.content == CANCELLED_MESSAGE


# --- Tools integradas -------------------------------------------------------


def test_builtin_tools_are_registered() -> None:
    assert build_registry().names() == ["get_reuniones", "enviar_mensaje"]


def test_only_tools_with_external_effects_require_confirmation() -> None:
    by_name = {tool.name: tool for tool in BUILTIN_TOOLS}

    assert not by_name["get_reuniones"].requires_confirmation
    assert by_name["enviar_mensaje"].requires_confirmation


def test_get_reuniones_returns_sample_meetings() -> None:
    data = json.loads(get_reuniones("2026-10-29"))  # jueves

    assert data["fecha"] == "2026-10-29"
    assert 2 <= len(data["reuniones"]) <= 3
    assert {"hora", "titulo", "con"} <= data["reuniones"][0].keys()


def test_get_reuniones_invalid_date_is_error() -> None:
    result = build_registry().execute("get_reuniones", {"fecha": "mañana"})

    assert result.is_error


def test_enviar_mensaje_shows_message_and_sends_when_confirmed() -> None:
    prompts: list[str] = []
    registry = build_registry(confirm=lambda prompt: prompts.append(prompt) or True)

    result = registry.execute("enviar_mensaje", {"destinatario": "Ana", "texto": "Llego tarde"})

    assert "Ana" in prompts[0] and "Llego tarde" in prompts[0]
    assert result.content == "Mensaje enviado a Ana (simulado)."
    assert ENVIAR_MENSAJE.requires_confirmation
