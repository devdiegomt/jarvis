"""Tools de JARVIS.

Para agregar una tool nueva: crea un archivo en este paquete que defina `TOOL`
y añádela a `BUILTIN_TOOLS`. No hace falta tocar `agent.py`.
"""

from jarvis.tools import mensajes, reuniones
from jarvis.tools.registry import Confirmer, Tool, ToolRegistry, ToolResult, deny_all

BUILTIN_TOOLS: list[Tool] = [reuniones.TOOL, mensajes.TOOL]


def build_registry(confirm: Confirmer = deny_all) -> ToolRegistry:
    """Crea un registro con todas las tools integradas."""
    registry = ToolRegistry(confirm=confirm)
    for tool in BUILTIN_TOOLS:
        registry.register(tool)
    return registry


__all__ = ["BUILTIN_TOOLS", "Confirmer", "Tool", "ToolRegistry", "ToolResult", "build_registry"]
