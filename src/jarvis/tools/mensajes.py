"""Tool simulada con efectos externos: envío de mensajes (requiere confirmación)."""

from typing import Any

from jarvis.tools.registry import Tool


def enviar_mensaje(destinatario: str, texto: str) -> str:
    """Simula el envío. Solo se llama después de que el usuario confirma."""
    return f"Mensaje enviado a {destinatario} (simulado)."


def _confirmation_prompt(tool_input: dict[str, Any]) -> str:
    return (
        "JARVIS quiere enviar un mensaje:\n"
        f"  Para:  {tool_input['destinatario']}\n"
        f"  Texto: {tool_input['texto']}"
    )


TOOL = Tool(
    name="enviar_mensaje",
    description=(
        "Envía un mensaje de texto a un contacto del usuario. "
        "El usuario debe confirmar el envío; si lo cancela, no insistas. "
        "Usa un texto claro y listo para enviar."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "destinatario": {
                "type": "string",
                "description": "Nombre o contacto de la persona que recibe el mensaje.",
            },
            "texto": {"type": "string", "description": "Contenido completo del mensaje."},
        },
        "required": ["destinatario", "texto"],
        "additionalProperties": False,
    },
    func=enviar_mensaje,
    confirmation_prompt=_confirmation_prompt,
)
