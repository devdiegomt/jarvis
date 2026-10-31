"""Tools de JARVIS.

Para agregar una tool nueva: crea un archivo en este paquete que defina la tool
y añádela en `build_tools`. No hace falta tocar `agent.py`.
"""

from collections.abc import Callable
from datetime import datetime, tzinfo

from jarvis.agenda import CalendarSource
from jarvis.config import WebSettings
from jarvis.long_term_memory import MemoryStore
from jarvis.reminders import ReminderStore
from jarvis.tasks import TaskStore
from jarvis.tools import internet, memoria, mensajes, pendientes, recordatorios, reuniones
from jarvis.tools.registry import Confirmer, Tool, ToolRegistry, ToolResult, deny_all


def build_tools(
    calendar: CalendarSource,
    reminders: ReminderStore | None = None,
    now: Callable[[], datetime] | None = None,
    tasks: TaskStore | None = None,
    memories: MemoryStore | None = None,
) -> list[Tool]:
    """Todas las tools integradas, con sus dependencias ya conectadas.

    Las de recordatorios y pendientes solo se incluyen si se pasa su almacén y el reloj (`now`);
    las de memoria, si se pasa `memories`.
    """
    tools = [reuniones.build_tool(calendar), mensajes.TOOL]
    if reminders is not None and now is not None:
        tools += recordatorios.build_tools(reminders, now)
    if tasks is not None and now is not None:
        tools += pendientes.build_tools(tasks, now)
    if memories is not None:
        tools += memoria.build_tools(memories)
    return tools


def build_registry(
    calendar: CalendarSource,
    confirm: Confirmer = deny_all,
    reminders: ReminderStore | None = None,
    now: Callable[[], datetime] | None = None,
    tasks: TaskStore | None = None,
    memories: MemoryStore | None = None,
    web: WebSettings | None = None,
    timezone: tzinfo | None = None,
) -> ToolRegistry:
    """Crea un registro con todas las tools integradas (y las de internet, si se pasa `web`)."""
    registry = ToolRegistry(confirm=confirm)
    for tool in build_tools(calendar, reminders, now, tasks, memories):
        registry.register(tool)
    for definition in internet.build_server_tools(web, timezone) if web is not None else []:
        registry.register_server_tool(definition)
    return registry


__all__ = ["Confirmer", "Tool", "ToolRegistry", "ToolResult", "build_registry", "build_tools"]
