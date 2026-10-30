"""Tools de recordatorios: crear, listar y cancelar.

Son acciones internas de JARVIS (no salen hacia nadie más), así que no piden confirmación:
JARVIS dice qué creó o canceló, y siempre se puede deshacer.
"""

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from jarvis.reminders import Reminder, ReminderStore
from jarvis.tools.registry import Tool

MAX_TEXT_LENGTH = 500
MAX_AHEAD = timedelta(days=365)
_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def build_tools(store: ReminderStore, now: Callable[[], datetime]) -> list[Tool]:
    """`now` devuelve la fecha y hora actuales en la zona horaria del usuario."""

    def crear_recordatorio(texto: str, fecha_hora: str | None = None, en_minutos: int | None = None) -> str:
        text = texto.strip()
        if not text:
            raise ValueError("El texto del recordatorio no puede estar vacío.")
        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError(f"El texto del recordatorio no puede superar {MAX_TEXT_LENGTH} caracteres.")
        current = now()
        due_at = _resolve_due(fecha_hora, en_minutos, current)
        if due_at <= current:
            raise ValueError(f"Esa fecha y hora ya pasó (ahora son las {_format(current)}).")
        if due_at - current > MAX_AHEAD:
            raise ValueError("Solo se pueden crear recordatorios para el próximo año.")
        reminder = store.create(text, due_at)
        return json.dumps({"creado": _to_dict(reminder, current)}, ensure_ascii=False)

    def listar_recordatorios() -> str:
        current = now()
        reminders = [_to_dict(r, current) for r in store.pending()]
        result: dict[str, Any] = {"ahora": _format(current), "recordatorios": reminders}
        if not reminders:
            result["mensaje"] = "No hay recordatorios pendientes."
        return json.dumps(result, ensure_ascii=False)

    def cancelar_recordatorio(id: int) -> str:  # noqa: A002 - nombre del parámetro visible para el modelo
        reminder = store.get(int(id))
        if reminder is None or not store.cancel(reminder.id):
            raise ValueError(f"No hay un recordatorio pendiente con id {id}. Usa listar_recordatorios.")
        return json.dumps({"cancelado": _to_dict(reminder, now())}, ensure_ascii=False)

    return [
        Tool(
            name="crear_recordatorio",
            description=(
                "Crea un recordatorio que JARVIS enviará al usuario por Telegram a la hora indicada. "
                "Usa `en_minutos` para plazos relativos (\"en 2 horas\" = 120) y `fecha_hora` para "
                "horas concretas (\"mañana a las 9\"), calculada a partir de la fecha y hora actuales. "
                "Indica solo uno de los dos. Después, dile al usuario qué creaste y para cuándo."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "texto": {"type": "string", "description": "Qué hay que recordar, breve y claro."},
                    "fecha_hora": {
                        "type": "string",
                        "description": "Fecha y hora local en formato YYYY-MM-DD HH:MM.",
                    },
                    "en_minutos": {
                        "type": "integer",
                        "description": "Minutos desde ahora (alternativa a fecha_hora).",
                    },
                },
                "required": ["texto"],
                "additionalProperties": False,
            },
            func=crear_recordatorio,
        ),
        Tool(
            name="listar_recordatorios",
            description=(
                "Lista los recordatorios pendientes del usuario (id, texto, fecha y hora), "
                "junto con la fecha y hora actuales."
            ),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            func=listar_recordatorios,
        ),
        Tool(
            name="cancelar_recordatorio",
            description=(
                "Cancela un recordatorio pendiente por su id. Si no conoces el id, "
                "usa primero listar_recordatorios."
            ),
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "Id del recordatorio."}},
                "required": ["id"],
                "additionalProperties": False,
            },
            func=cancelar_recordatorio,
        ),
    ]


def _resolve_due(fecha_hora: str | None, en_minutos: int | None, current: datetime) -> datetime:
    if (fecha_hora is None) == (en_minutos is None):
        raise ValueError("Indica fecha_hora o en_minutos (solo uno de los dos).")
    if en_minutos is not None:
        return current + timedelta(minutes=int(en_minutos))
    assert fecha_hora is not None
    for fmt in _FORMATS:
        try:
            return datetime.strptime(fecha_hora.strip(), fmt).replace(tzinfo=current.tzinfo)
        except ValueError:
            continue
    raise ValueError(f"fecha_hora='{fecha_hora}' no es válida; usa el formato YYYY-MM-DD HH:MM.")


def _to_dict(reminder: Reminder, current: datetime) -> dict[str, Any]:
    return {
        "id": reminder.id,
        "texto": reminder.text,
        "fecha_hora": _format(reminder.due_at.astimezone(current.tzinfo)),
    }


def _format(moment: datetime) -> str:
    return f"{moment:%Y-%m-%d %H:%M}"
