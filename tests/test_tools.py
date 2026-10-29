import json
from datetime import UTC, date, datetime

import pytest

from jarvis.agenda import CalendarError, Meeting, SampleCalendar
from jarvis.tools import Tool, ToolRegistry, build_registry, build_tools
from jarvis.tools.mensajes import TOOL as ENVIAR_MENSAJE
from jarvis.tools.registry import CANCELLED_MESSAGE, ToolResult

SAMPLE = SampleCalendar(UTC)

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
    result = build_registry(SAMPLE).execute("enviar_mensaje", {"destinatario": "Ana", "texto": "Hola"})

    assert result.content == CANCELLED_MESSAGE


# --- Tools integradas -------------------------------------------------------


def test_builtin_tools_are_registered() -> None:
    assert build_registry(SAMPLE).names() == ["get_reuniones", "enviar_mensaje"]


def test_only_tools_with_external_effects_require_confirmation() -> None:
    by_name = {tool.name: tool for tool in build_tools(SAMPLE)}

    assert not by_name["get_reuniones"].requires_confirmation
    assert by_name["enviar_mensaje"].requires_confirmation


class FakeCalendar:
    name = "falso"

    def __init__(self, meetings: list[Meeting] | None = None, error: Exception | None = None) -> None:
        self.meetings = meetings or []
        self.error = error
        self.calls: list[tuple[date, date]] = []

    def list_meetings(self, start: date, end: date) -> list[Meeting]:
        self.calls.append((start, end))
        if self.error:
            raise self.error
        return self.meetings


def run_get_reuniones(calendar: FakeCalendar, **tool_input: str) -> ToolResult:
    return build_registry(calendar).execute("get_reuniones", tool_input)


def test_get_reuniones_single_day_formats_meetings() -> None:
    calendar = FakeCalendar(
        [
            Meeting(
                title="Demo",
                start=datetime(2026, 10, 29, 9, 30, tzinfo=UTC),
                end=datetime(2026, 10, 29, 10, 0, tzinfo=UTC),
                location="Sala 1",
                attendees=("Ana",),
            ),
            Meeting(title="Festivo", start=date(2026, 10, 29), end=date(2026, 10, 29), all_day=True),
        ]
    )

    result = run_get_reuniones(calendar, fecha="2026-10-29")
    data = json.loads(result.content)

    assert not result.is_error
    assert calendar.calls == [(date(2026, 10, 29), date(2026, 10, 29))]
    assert data["desde"] == data["hasta"] == "2026-10-29"
    assert data["reuniones"] == [
        {
            "titulo": "Demo",
            "inicio": "2026-10-29 09:30",
            "fin": "2026-10-29 10:00",
            "todo_el_dia": False,
            "ubicacion": "Sala 1",
            "participantes": ["Ana"],
        },
        {"titulo": "Festivo", "inicio": "2026-10-29", "fin": "2026-10-29", "todo_el_dia": True},
    ]


def test_get_reuniones_with_range() -> None:
    calendar = FakeCalendar()

    run_get_reuniones(calendar, fecha="2026-10-26", fecha_fin="2026-10-30")

    assert calendar.calls == [(date(2026, 10, 26), date(2026, 10, 30))]


def test_get_reuniones_empty_day_says_so() -> None:
    data = json.loads(run_get_reuniones(FakeCalendar(), fecha="2026-10-29").content)

    assert data["reuniones"] == []
    assert "No hay reuniones" in data["mensaje"]


@pytest.mark.parametrize(
    ("tool_input", "expected"),
    [
        ({"fecha": "mañana"}, "YYYY-MM-DD"),
        ({"fecha": "2026-10-29", "fecha_fin": "2026-10-28"}, "anterior"),
        ({"fecha": "2026-10-01", "fecha_fin": "2026-10-15"}, "14 días"),
    ],
)
def test_get_reuniones_invalid_dates_are_errors(tool_input: dict, expected: str) -> None:
    calendar = FakeCalendar()

    result = run_get_reuniones(calendar, **tool_input)

    assert result.is_error
    assert expected in result.content
    assert calendar.calls == []


def test_get_reuniones_calendar_error_goes_back_to_model() -> None:
    result = run_get_reuniones(FakeCalendar(error=CalendarError("Sin conexión")), fecha="2026-10-29")

    assert result.is_error
    assert "Sin conexión" in result.content


def test_sample_calendar_has_fewer_meetings_on_weekends() -> None:
    weekday = SAMPLE.list_meetings(date(2026, 10, 29), date(2026, 10, 29))  # jueves
    saturday = SAMPLE.list_meetings(date(2026, 10, 31), date(2026, 10, 31))

    assert len(weekday) == 3
    assert len(saturday) == 2
    assert all(m.start.date() == date(2026, 10, 29) for m in weekday)


def test_enviar_mensaje_shows_message_and_sends_when_confirmed() -> None:
    prompts: list[str] = []
    registry = build_registry(SAMPLE, confirm=lambda prompt: prompts.append(prompt) or True)

    result = registry.execute("enviar_mensaje", {"destinatario": "Ana", "texto": "Llego tarde"})

    assert "Ana" in prompts[0] and "Llego tarde" in prompts[0]
    assert result.content == "Mensaje enviado a Ana (simulado)."
    assert ENVIAR_MENSAJE.requires_confirmation
