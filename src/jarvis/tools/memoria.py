"""Tools de memoria a largo plazo: recordar, listar y olvidar datos del usuario.

Son datos internos de JARVIS y se pueden borrar (con `olvidar_dato` o /memoria), así que no
piden confirmación; el system prompt pide al modelo avisar cuando recuerda algo.
"""

import json

from jarvis.long_term_memory import MAX_MEMORY_LENGTH, Memory, MemoryLimitError, MemoryStore
from jarvis.sensitive import has_long_number
from jarvis.tools.registry import Tool


def build_tools(store: MemoryStore) -> list[Tool]:
    def recordar_dato(dato: str) -> str:
        text = " ".join(dato.split())
        if not text:
            raise ValueError("El dato no puede estar vacío.")
        if len(text) > MAX_MEMORY_LENGTH:
            raise ValueError(f"El dato no puede superar {MAX_MEMORY_LENGTH} caracteres: resúmelo.")
        if has_long_number(text):
            raise ValueError(
                "No guardo números largos (tarjetas, cuentas, documentos) en la memoria. "
                "Dile al usuario que por seguridad no lo recordarás."
            )
        try:
            memory, is_new = store.add(text)
        except MemoryLimitError as exc:
            raise ValueError(f"{exc} Pide al usuario que borre alguno con /memoria.") from exc
        key = "recordado" if is_new else "ya_lo_sabias"
        return json.dumps({key: _to_dict(memory)}, ensure_ascii=False)

    def listar_datos() -> str:
        memories = [_to_dict(m) for m in store.all()]
        result: dict[str, object] = {"datos": memories}
        if not memories:
            result["mensaje"] = "Aún no recuerdas nada del usuario."
        return json.dumps(result, ensure_ascii=False)

    def olvidar_dato(id: int) -> str:  # noqa: A002 - nombre del parámetro visible para el modelo
        memory = store.delete(int(id))
        if memory is None:
            raise ValueError(f"No hay un dato guardado con id {id}. Usa listar_datos.")
        return json.dumps({"olvidado": _to_dict(memory)}, ensure_ascii=False)

    return [
        Tool(
            name="recordar_dato",
            description=(
                "Guarda en la memoria a largo plazo un dato duradero sobre el usuario, para "
                "recordarlo en futuras conversaciones: personas de su entorno, preferencias, rutinas, "
                "datos de su trabajo. Úsalo por iniciativa propia cuando el usuario cuente algo que "
                "seguirá siendo cierto, escrito como una frase corta y autónoma (\"Su socia se llama "
                "Laura y prefiere reuniones por la mañana\"). No guardes cosas pasajeras (lo de hoy), "
                "lo que ya está en la memoria, ni contraseñas o datos bancarios."
            ),
            input_schema={
                "type": "object",
                "properties": {"dato": {"type": "string", "description": "El dato, en una frase corta."}},
                "required": ["dato"],
                "additionalProperties": False,
            },
            func=recordar_dato,
        ),
        Tool(
            name="listar_datos",
            description="Lista los datos guardados en la memoria a largo plazo, con su id.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            func=listar_datos,
        ),
        Tool(
            name="olvidar_dato",
            description=(
                "Borra un dato de la memoria a largo plazo por su id: cuando el usuario lo pide o "
                "cuando un dato dejó de ser cierto (en ese caso, guarda después el dato nuevo)."
            ),
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "Id del dato."}},
                "required": ["id"],
                "additionalProperties": False,
            },
            func=olvidar_dato,
        ),
    ]


def _to_dict(memory: Memory) -> dict[str, object]:
    return {"id": memory.id, "dato": memory.text}
