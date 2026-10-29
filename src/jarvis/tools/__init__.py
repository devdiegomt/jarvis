"""Tools de JARVIS.

Para agregar una tool nueva: crea un archivo en este paquete que defina la tool
y añádela en `build_tools`. No hace falta tocar `agent.py`.
"""

from jarvis.agenda import CalendarSource
from jarvis.tools import mensajes, reuniones
from jarvis.tools.registry import Confirmer, Tool, ToolRegistry, ToolResult, deny_all


def build_tools(calendar: CalendarSource) -> list[Tool]:
    """Todas las tools integradas, con sus dependencias ya conectadas."""
    return [reuniones.build_tool(calendar), mensajes.TOOL]


def build_registry(calendar: CalendarSource, confirm: Confirmer = deny_all) -> ToolRegistry:
    """Crea un registro con todas las tools integradas."""
    registry = ToolRegistry(confirm=confirm)
    for tool in build_tools(calendar):
        registry.register(tool)
    return registry


__all__ = ["Confirmer", "Tool", "ToolRegistry", "ToolResult", "build_registry", "build_tools"]
