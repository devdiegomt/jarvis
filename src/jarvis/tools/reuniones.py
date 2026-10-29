"""Tool simulada de solo lectura: reuniones del día."""

import json
from datetime import date

from jarvis.tools.registry import Tool

_SAMPLE_MEETINGS: list[dict[str, str]] = [
    {"hora": "09:30", "duracion": "30 min", "titulo": "Daily del equipo", "con": "Equipo de producto"},
    {"hora": "12:00", "duracion": "1 h", "titulo": "Revisión de propuesta", "con": "Laura Gómez (cliente)"},
    {"hora": "16:30", "duracion": "45 min", "titulo": "Planificación semanal", "con": "Carlos Ruiz"},
]


def get_reuniones(fecha: str) -> str:
    """Devuelve reuniones de ejemplo para la fecha indicada (YYYY-MM-DD)."""
    day = date.fromisoformat(fecha)
    # Los fines de semana hay menos reuniones, para que los datos parezcan realistas.
    meetings = _SAMPLE_MEETINGS[1:] if day.weekday() >= 5 else _SAMPLE_MEETINGS
    return json.dumps({"fecha": day.isoformat(), "reuniones": meetings}, ensure_ascii=False)


TOOL = Tool(
    name="get_reuniones",
    description=(
        "Obtiene las reuniones del usuario para una fecha concreta. "
        "Úsala cuando el usuario pregunte por su agenda, reuniones o disponibilidad. "
        "Devuelve JSON con hora, duración, título y participantes de cada reunión."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fecha": {
                "type": "string",
                "description": "Fecha en formato ISO YYYY-MM-DD, por ejemplo 2026-10-29.",
            }
        },
        "required": ["fecha"],
        "additionalProperties": False,
    },
    func=get_reuniones,
)
