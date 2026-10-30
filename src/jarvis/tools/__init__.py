"""Tools de JARVIS.

Para agregar una tool nueva: crea un archivo en este paquete que defina la tool
y añádela en `build_tools`. No hace falta tocar `agent.py`.
"""

from collections.abc import Callable
from datetime import datetime

from jarvis.agenda import CalendarSource
from jarvis.reminders import ReminderStore
from jarvis.tools import mensajes, recordatorios, reuniones
from jarvis.tools.registry import Confirmer, Tool, ToolRegistry, ToolResult, deny_all


def build_tools(
    calendar: CalendarSource,
    reminders: ReminderStore | None = None,
    now: Callable[[], datetime] | None = None,
) -> list[Tool]:
    """Todas las tools integradas, con sus dependencias ya conectadas.

    Las de recordatorios solo se incluyen si se pasa el almacén (`reminders`) y el reloj (`now`).
    """
    tools = [reuniones.build_tool(calendar), mensajes.TOOL]
    if reminders is not None and now is not None:
        tools += recordatorios.build_tools(reminders, now)
    return tools


def build_registry(
    calendar: CalendarSource,
    confirm: Confirmer = deny_all,
    reminders: ReminderStore | None = None,
    now: Callable[[], datetime] | None = None,
) -> ToolRegistry:
    """Crea un registro con todas las tools integradas."""
    registry = ToolRegistry(confirm=confirm)
    for tool in build_tools(calendar, reminders, now):
        registry.register(tool)
    return registry


__all__ = ["Confirmer", "Tool", "ToolRegistry", "ToolResult", "build_registry", "build_tools"]
