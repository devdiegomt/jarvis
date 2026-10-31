"""Tools de pendientes: agregar, listar, completar y borrar.

Como los recordatorios, son datos internos de JARVIS y no piden confirmación.
"""

import json
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from jarvis.tasks import Task, TaskLimitError, TaskStore
from jarvis.tools.registry import Tool

MAX_TEXT_LENGTH = 500


def build_tools(store: TaskStore, now: Callable[[], datetime]) -> list[Tool]:
    """`now` devuelve la fecha y hora actuales en la zona horaria del usuario."""

    def agregar_pendiente(texto: str, fecha_limite: str | None = None) -> str:
        text = texto.strip()
        if not text:
            raise ValueError("El texto del pendiente no puede estar vacío.")
        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError(f"El texto del pendiente no puede superar {MAX_TEXT_LENGTH} caracteres.")
        due_date = _parse_date(fecha_limite) if fecha_limite else None
        try:
            task = store.add(text, due_date)
        except TaskLimitError as exc:
            raise ValueError(f"{exc} Pide al usuario que complete o borre alguno.") from exc
        return json.dumps({"agregado": _to_dict(task, now().date())}, ensure_ascii=False)

    def listar_pendientes() -> str:
        today = now().date()
        tasks = [_to_dict(task, today) for task in store.open()]
        result: dict[str, Any] = {"hoy": today.isoformat(), "pendientes": tasks}
        if not tasks:
            result["mensaje"] = "No hay pendientes abiertos."
        return json.dumps(result, ensure_ascii=False)

    def completar_pendiente(id: int) -> str:  # noqa: A002 - nombre del parámetro visible para el modelo
        task = store.get(int(id))
        if task is None or not store.complete(task.id):
            raise ValueError(f"No hay un pendiente abierto con id {id}. Usa listar_pendientes.")
        return json.dumps({"completado": _to_dict(task, now().date())}, ensure_ascii=False)

    def borrar_pendiente(id: int) -> str:  # noqa: A002
        task = store.get(int(id))
        if task is None or not store.delete(task.id):
            raise ValueError(f"No hay un pendiente con id {id}. Usa listar_pendientes.")
        return json.dumps({"borrado": _to_dict(task, now().date())}, ensure_ascii=False)

    id_schema = {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "Id del pendiente."}},
        "required": ["id"],
        "additionalProperties": False,
    }
    return [
        Tool(
            name="agregar_pendiente",
            description=(
                "Agrega algo a la lista de pendientes del usuario: cosas por hacer sin hora fija "
                "(\"tengo que renovar el pasaporte\"). Si el usuario menciona un plazo, ponlo en "
                "`fecha_limite`. Si quiere que le avisen a una hora concreta, usa crear_recordatorio."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "texto": {"type": "string", "description": "Qué hay que hacer, breve y claro."},
                    "fecha_limite": {
                        "type": "string",
                        "description": "Fecha límite opcional, en formato YYYY-MM-DD.",
                    },
                },
                "required": ["texto"],
                "additionalProperties": False,
            },
            func=agregar_pendiente,
        ),
        Tool(
            name="listar_pendientes",
            description=(
                "Lista los pendientes abiertos (id, texto, fecha límite y si están atrasados), "
                "con la fecha de hoy."
            ),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            func=listar_pendientes,
        ),
        Tool(
            name="completar_pendiente",
            description="Marca un pendiente como hecho, por su id. Si no lo conoces, usa listar_pendientes.",
            input_schema=id_schema,
            func=completar_pendiente,
        ),
        Tool(
            name="borrar_pendiente",
            description=(
                "Borra un pendiente que ya no hace falta (no lo marca como hecho), por su id. "
                "Si no lo conoces, usa listar_pendientes."
            ),
            input_schema=id_schema,
            func=borrar_pendiente,
        ),
    ]


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(f"fecha_limite='{value}' no es válida; usa el formato YYYY-MM-DD.") from None


def _to_dict(task: Task, today: date) -> dict[str, Any]:
    result: dict[str, Any] = {"id": task.id, "texto": task.text}
    if task.due_date is not None:
        result["fecha_limite"] = task.due_date.isoformat()
        result["atrasado"] = task.due_date < today
    return result
