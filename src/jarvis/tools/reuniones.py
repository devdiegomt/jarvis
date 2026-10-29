"""Tool de solo lectura: reuniones del usuario en una fecha o rango de fechas."""

import json
from datetime import date
from typing import Any

from jarvis.agenda import CalendarSource, Meeting
from jarvis.tools.registry import Tool

MAX_RANGE_DAYS = 14


def build_tool(calendar: CalendarSource) -> Tool:
    """Crea la tool `get_reuniones` conectada a la fuente de calendario indicada."""

    def get_reuniones(fecha: str, fecha_fin: str | None = None) -> str:
        start = _parse_date(fecha, "fecha")
        end = _parse_date(fecha_fin, "fecha_fin") if fecha_fin else start
        if end < start:
            raise ValueError("fecha_fin no puede ser anterior a fecha.")
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            raise ValueError(f"El rango máximo es de {MAX_RANGE_DAYS} días.")

        meetings = calendar.list_meetings(start, end)
        result: dict[str, Any] = {
            "desde": start.isoformat(),
            "hasta": end.isoformat(),
            "reuniones": [_meeting_to_dict(m) for m in meetings],
        }
        if not meetings:
            result["mensaje"] = "No hay reuniones en ese periodo."
        return json.dumps(result, ensure_ascii=False)

    return Tool(
        name="get_reuniones",
        description=(
            "Obtiene las reuniones y eventos del calendario del usuario para una fecha "
            f"o un rango de hasta {MAX_RANGE_DAYS} días. Úsala cuando pregunte por su agenda, "
            "reuniones o disponibilidad. Devuelve JSON con título, inicio, fin, si es de día "
            "completo, ubicación y participantes. Las horas están en la zona horaria del usuario."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "fecha": {
                    "type": "string",
                    "description": "Fecha (o inicio del rango) en formato YYYY-MM-DD.",
                },
                "fecha_fin": {
                    "type": "string",
                    "description": "Opcional. Último día del rango (incluido), formato YYYY-MM-DD.",
                },
            },
            "required": ["fecha"],
            "additionalProperties": False,
        },
        func=get_reuniones,
    )


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field}='{value}' no es válida; usa el formato YYYY-MM-DD.") from exc


def _meeting_to_dict(meeting: Meeting) -> dict[str, Any]:
    if meeting.all_day:
        start, end = meeting.start.isoformat(), meeting.end.isoformat()
    else:
        start, end = (f"{dt:%Y-%m-%d %H:%M}" for dt in (meeting.start, meeting.end))
    data: dict[str, Any] = {
        "titulo": meeting.title,
        "inicio": start,
        "fin": end,
        "todo_el_dia": meeting.all_day,
    }
    if meeting.location:
        data["ubicacion"] = meeting.location
    if meeting.attendees:
        data["participantes"] = list(meeting.attendees)
    return data
