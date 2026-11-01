"""Detección de datos que JARVIS nunca guarda (tarjetas, cuentas, documentos)."""

import re

# Secuencias largas de dígitos (12 o más, con espacios o guiones opcionales).
LONG_NUMBER = re.compile(r"\d(?:[ -]?\d){11,}")


def has_long_number(text: str) -> bool:
    return LONG_NUMBER.search(text) is not None
