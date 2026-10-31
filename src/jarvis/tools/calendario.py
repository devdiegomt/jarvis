"""Tools para escribir en el calendario: agendar, mover y cancelar eventos.

Tienen efectos externos, así que siempre piden confirmación al usuario con el detalle de lo que
van a hacer (y de los choques de horario). Solo tocan eventos que organiza el usuario: las
invitaciones de otras personas no se mueven ni se cancelan, y nunca se avisa a nadie.
"""

import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from jarvis.agenda import Meeting, WritableCalendar, meeting_to_dict
from jarvis.summary import format_spanish_date
from jarvis.tools.registry import Tool

DEFAULT_DURATION_MINUTES = 60
MAX_DURATION_MINUTES = 24 * 60
MAX_TITLE_LENGTH = 200
MAX_AHEAD = timedelta(days=2 * 365)
_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")

logger = logging.getLogger("jarvis.chat")


def build_tools(calendar: WritableCalendar, now: Callable[[], datetime]) -> list[Tool]:
    """`now` devuelve la fecha y hora actuales en la zona horaria del usuario."""

    def new_event(tool_input: dict[str, Any]) -> tuple[str, datetime, datetime]:
        title = str(tool_input["titulo"]).strip()
        if not title or len(title) > MAX_TITLE_LENGTH:
            raise ValueError(f"El título debe tener entre 1 y {MAX_TITLE_LENGTH} caracteres.")
        start = _parse(tool_input["inicio"], "inicio", now())
        current = now()
        if start < current - timedelta(minutes=1):
            raise ValueError(f"Esa hora ya pasó (ahora son las {current:%Y-%m-%d %H:%M}).")
        if start - current > MAX_AHEAD:
            raise ValueError("Solo puedo agendar eventos para los próximos dos años.")
        return title, start, start + _duration(tool_input.get("duracion_minutos"), DEFAULT_DURATION_MINUTES)

    def own_event(event_id: str) -> Meeting:
        meeting = calendar.get_event(str(event_id))
        if meeting is None:
            raise ValueError(f"No encontré el evento con id {event_id}. Usa get_reuniones para ver los ids.")
        if not meeting.organized_by_me:
            raise ValueError(
                "Ese evento lo organiza otra persona: JARVIS no mueve ni cancela invitaciones. "
                "Dile al usuario que lo responda desde Google Calendar."
            )
        return meeting

    def moved_times(tool_input: dict[str, Any]) -> tuple[Meeting, datetime, datetime]:
        meeting = own_event(tool_input["id"])
        if meeting.all_day:
            raise ValueError("Por ahora solo puedo mover eventos con hora, no los de día completo.")
        current_minutes = int((meeting.end - meeting.start).total_seconds() // 60)  # type: ignore[operator]
        start = _parse(tool_input["nuevo_inicio"], "nuevo_inicio", now())
        if start < now() - timedelta(minutes=1):
            raise ValueError("Esa hora ya pasó.")
        return meeting, start, start + _duration(tool_input.get("duracion_minutos"), current_minutes)

    def conflicts(start: datetime, end: datetime, ignore_id: str | None = None) -> str:
        busy = [
            m
            for m in calendar.list_meetings(start.date(), end.date())
            if not m.all_day and m.id != ignore_id and m.start < end and m.end > start  # type: ignore[operator]
        ]
        if not busy:
            return ""
        names = ", ".join(f"«{m.title}» ({m.start:%H:%M}-{m.end:%H:%M})" for m in busy)
        return f"\n⚠ Choca con: {names}"

    def confirm_create(tool_input: dict[str, Any]) -> str:
        title, start, end = new_event(tool_input)
        lines = [f"Voy a agendar en tu calendario:\n«{title}»\n{_when(start, end)}"]
        if tool_input.get("ubicacion"):
            lines.append(f"Lugar: {tool_input['ubicacion']}")
        return "\n".join(lines) + conflicts(start, end)

    def confirm_move(tool_input: dict[str, Any]) -> str:
        meeting, start, end = moved_times(tool_input)
        before = _when(meeting.start, meeting.end)  # type: ignore[arg-type]
        text = f"Voy a mover «{meeting.title}»\nde: {before}\na: {_when(start, end)}"
        if meeting.recurring:
            text += "\n(Se repite: solo cambia esta vez.)"
        return text + conflicts(start, end, ignore_id=meeting.id)

    def confirm_cancel(tool_input: dict[str, Any]) -> str:
        meeting = own_event(tool_input["id"])
        if meeting.all_day:
            when = f"{format_spanish_date(meeting.start)} (todo el día)"  # type: ignore[arg-type]
        else:
            when = _when(meeting.start, meeting.end)  # type: ignore[arg-type]
        text = f"Voy a cancelar «{meeting.title}»\n{when}"
        if meeting.recurring:
            text += "\n(Se repite: solo se cancela esta vez.)"
        return text

    def crear_evento(
        titulo: str,
        inicio: str,
        duracion_minutos: int | None = None,
        ubicacion: str | None = None,
        descripcion: str | None = None,
    ) -> str:
        args = {"titulo": titulo, "inicio": inicio, "duracion_minutos": duracion_minutos}
        title, start, end = new_event(args)
        location = (ubicacion or "").strip() or None
        meeting = calendar.create_event(title, start, end, location, (descripcion or "").strip() or None)
        logger.info("Evento creado en el calendario.")  # sin el título: el registro no guarda contenido
        return json.dumps({"creado": meeting_to_dict(meeting)}, ensure_ascii=False)

    def mover_evento(id: str, nuevo_inicio: str, duracion_minutos: int | None = None) -> str:  # noqa: A002
        args = {"id": id, "nuevo_inicio": nuevo_inicio, "duracion_minutos": duracion_minutos}
        meeting, start, end = moved_times(args)
        moved = calendar.move_event(str(meeting.id), start, end)
        logger.info("Evento movido en el calendario.")
        return json.dumps({"movido": meeting_to_dict(moved)}, ensure_ascii=False)

    def cancelar_evento(id: str) -> str:  # noqa: A002
        meeting = own_event(id)
        calendar.delete_event(str(meeting.id))
        logger.info("Evento cancelado en el calendario.")
        return json.dumps({"cancelado": meeting_to_dict(meeting)}, ensure_ascii=False)

    duration_schema = {
        "type": "integer",
        "description": f"Minutos (al crear, {DEFAULT_DURATION_MINUTES} por defecto; al mover, la actual).",
    }
    id_schema = {"type": "string", "description": "Id del evento, tal como lo devuelve get_reuniones."}
    return [
        Tool(
            name="crear_evento",
            description=(
                "Agenda un evento en el calendario del usuario (solo para él: no invita a nadie). "
                "Antes, revisa su agenda con get_reuniones. La hora es local, en formato YYYY-MM-DD HH:MM. "
                "Si solo quiere que le avisen de algo, usa crear_recordatorio; si es algo por hacer sin "
                "hora, agregar_pendiente."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "titulo": {"type": "string", "description": "Título corto del evento."},
                    "inicio": {"type": "string", "description": "Fecha y hora local, YYYY-MM-DD HH:MM."},
                    "duracion_minutos": duration_schema,
                    "ubicacion": {"type": "string", "description": "Opcional. Lugar o enlace."},
                    "descripcion": {"type": "string", "description": "Opcional. Notas del evento."},
                },
                "required": ["titulo", "inicio"],
                "additionalProperties": False,
            },
            func=crear_evento,
            confirmation_prompt=confirm_create,
        ),
        Tool(
            name="mover_evento",
            description=(
                "Cambia la hora (y opcionalmente la duración) de un evento que organiza el usuario. "
                "Obtén el id con get_reuniones; las invitaciones de otras personas no se pueden mover."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "id": id_schema,
                    "nuevo_inicio": {"type": "string", "description": "Nueva hora local, YYYY-MM-DD HH:MM."},
                    "duracion_minutos": duration_schema,
                },
                "required": ["id", "nuevo_inicio"],
                "additionalProperties": False,
            },
            func=mover_evento,
            confirmation_prompt=confirm_move,
        ),
        Tool(
            name="cancelar_evento",
            description=(
                "Cancela (borra) un evento que organiza el usuario. Obtén el id con get_reuniones; "
                "las invitaciones de otras personas no se pueden cancelar desde aquí."
            ),
            input_schema={
                "type": "object",
                "properties": {"id": id_schema},
                "required": ["id"],
                "additionalProperties": False,
            },
            func=cancelar_evento,
            confirmation_prompt=confirm_cancel,
        ),
    ]


def _parse(value: object, field: str, current: datetime) -> datetime:
    for fmt in _FORMATS:
        try:
            return datetime.strptime(str(value).strip(), fmt).replace(tzinfo=current.tzinfo)
        except ValueError:
            continue
    raise ValueError(f"{field}='{value}' no es válido; usa el formato YYYY-MM-DD HH:MM.")


def _duration(minutes: object, default: int) -> timedelta:
    value = default if minutes is None else int(minutes)  # type: ignore[call-overload]
    if not 5 <= value <= MAX_DURATION_MINUTES:
        raise ValueError(f"La duración debe estar entre 5 y {MAX_DURATION_MINUTES} minutos.")
    return timedelta(minutes=value)


def _when(start: datetime, end: datetime) -> str:
    """Por ejemplo: `jueves 6 de noviembre, 15:00 a 16:00`."""
    if start.date() == end.date():
        return f"{format_spanish_date(start.date())}, {start:%H:%M} a {end:%H:%M}"
    return f"{format_spanish_date(start.date())} {start:%H:%M} a {format_spanish_date(end.date())} {end:%H:%M}"
