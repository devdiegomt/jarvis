"""Resumen diario: genera el texto con las reuniones del día y lo envía."""

import json
import time as time_module
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import TypeVar

import anthropic

from jarvis.agenda import (
    CalendarError,
    CalendarNotAuthorizedError,
    CalendarSource,
    Meeting,
    meeting_to_dict,
    meeting_to_line,
)
from jarvis.notify import NotificationError, NotificationNotAuthorizedError, Notifier
from jarvis.dates import format_spanish_date
from jarvis.storage import SummaryLog
from jarvis.tasks import Task, TaskStore
from jarvis.usage import Usage, UsageLog, usage_from_response

HIGHLIGHTS_MAX_TOKENS = 4000


HIGHLIGHTS_PROMPT = """\
Eres JARVIS, el asistente personal del usuario. Escribe el comentario inicial de su resumen \
matutino por correo, en español.

Recibirás las reuniones del día y los pendientes que vencen hoy (o están atrasados) en JSON. En 2 \
a 4 frases destaca lo más importante: choques de horario, huecos libres útiles (por ejemplo, para \
avanzar en un pendiente) y lo que convenga preparar. Escribe en texto plano, sin markdown, sin \
viñetas, sin saludo ni despedida. No inventes nada que no esté en los datos. Las listas completas \
de reuniones y pendientes se añaden aparte: no las repitas."""

NO_MEETINGS_NOTE = "Hoy no tienes reuniones en el calendario: buen día para avanzar en tus pendientes."
FALLBACK_NOTE = "(Hoy no pude preparar el comentario del día; aquí tienes tu agenda.)"


@dataclass(frozen=True)
class DailySummary:
    subject: str
    body: str
    meetings_count: int
    ai_generated: bool


def build_summary(
    day: date,
    meetings: list[Meeting],
    highlights: str | None,
    source_name: str,
    tasks: Sequence[Task] = (),
    weather: str | None = None,
) -> DailySummary:
    """Arma el correo. La agenda se genera en código para que las horas sean siempre exactas.

    `tasks` son los pendientes que vencen ese día o están atrasados; `weather`, la línea del clima.
    """
    count = len(meetings)
    if count == 0:
        count_text = "sin reuniones"
    else:
        count_text = f"{count} {'reunión' if count == 1 else 'reuniones'}"
    if tasks:
        count_text += f", {len(tasks)} {'pendiente' if len(tasks) == 1 else 'pendientes'}"
    subject = f"Tu día: {format_spanish_date(day)} ({count_text})"

    if not meetings:
        note, agenda = NO_MEETINGS_NOTE, ""
    else:
        note = highlights or FALLBACK_NOTE
        agenda = "\n\nAgenda:\n" + "\n".join(f"- {meeting_to_line(m)}" for m in meetings)

    pending = ""
    if tasks:
        pending = "\n\nPendientes para hoy:\n" + "\n".join(f"- {task_to_line(t, day)}" for t in tasks)

    weather_note = f"Clima: {weather}\n\n" if weather else ""
    body = (
        f"Buenos días. Este es tu resumen del {format_spanish_date(day)}.\n\n"
        f"{weather_note}"
        f"{note}{agenda}{pending}\n\n"
        f"--\nJARVIS · Calendario: {source_name}"
    )
    return DailySummary(subject, body, count, ai_generated=bool(meetings and highlights))


def task_to_line(task: Task, day: date) -> str:
    if task.due_date is not None and task.due_date < day:
        return f"{task.text} (atrasado: era para el {task.due_date:%d/%m})"
    return task.text


def write_highlights(
    client: anthropic.Anthropic,
    model: str,
    day: date,
    meetings: list[Meeting],
    tasks: Sequence[Task] = (),
    record: Callable[[Usage], None] | None = None,
) -> str | None:
    """Pide a Claude el comentario del día. Devuelve None si no se pudo generar.

    `record` recibe los tokens usados (para medir el gasto).
    """
    payload = {
        "fecha": day.isoformat(),
        "dia": format_spanish_date(day),
        "reuniones": [meeting_to_dict(m) for m in meetings],
        "pendientes": [task_to_line(t, day) for t in tasks],
    }
    try:
        response = client.messages.create(
            model=model,
            max_tokens=HIGHLIGHTS_MAX_TOKENS,
            system=HIGHLIGHTS_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )
    except anthropic.APIError:
        return None
    if record is not None:
        record(usage_from_response(response))
    if response.stop_reason != "end_turn":
        return None  # rechazo o respuesta cortada: mejor el resumen simple
    text = "\n".join(block.text for block in response.content if block.type == "text").strip()
    return text or None


def send_daily_summary(
    *,
    day: date,
    calendar: CalendarSource,
    notifier: Notifier,
    client: anthropic.Anthropic,
    model: str,
    log: SummaryLog | None,
    now: Callable[[], datetime],
    force: bool = False,
    tasks: TaskStore | None = None,
    weather: Callable[[date], str | None] | None = None,
    usage_log: UsageLog | None = None,
) -> DailySummary | None:
    """Genera y envía el resumen del día. Devuelve None si ya se había enviado.

    Con `log=None` (modo de prueba) no se consulta ni se registra el envío.
    """
    if log is not None and not force and log.was_sent(day):
        return None
    meetings = calendar.list_meetings(day, day)
    due_tasks = tasks.due_by(day) if tasks is not None else []
    record = (lambda usage: usage_log.record("resumen", model, usage)) if usage_log is not None else None
    highlights = write_highlights(client, model, day, meetings, due_tasks, record) if meetings else None
    weather_line = weather(day) if weather is not None else None
    summary = build_summary(day, meetings, highlights, calendar.name, due_tasks, weather_line)
    notifier.send(summary.subject, summary.body)
    if log is not None:
        log.record_sent(day, now())
    return summary


T = TypeVar("T")

# Fallos temporales (red, Google caído). Los de autorización no se reintentan.
RETRYABLE_ERRORS = (CalendarError, NotificationError)
PERMANENT_ERRORS = (CalendarNotAuthorizedError, NotificationNotAuthorizedError)


def run_with_retries(
    action: Callable[[], T],
    attempts: int,
    wait_seconds: float,
    on_retry: Callable[[int, Exception], None] = lambda _attempt, _exc: None,
    sleep: Callable[[float], None] = time_module.sleep,
) -> T:
    """Ejecuta `action`, reintentando ante fallos temporales."""
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except PERMANENT_ERRORS:
            raise
        except RETRYABLE_ERRORS as exc:
            if attempt == attempts:
                raise
            on_retry(attempt, exc)
            sleep(wait_seconds)
    raise AssertionError("inalcanzable")
