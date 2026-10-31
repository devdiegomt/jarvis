"""Fechas en español, comunes a los textos que arma JARVIS (resumen, avisos, clima)."""

from datetime import date

WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def format_spanish_date(day: date) -> str:
    """Por ejemplo: `jueves 29 de octubre`."""
    return f"{WEEKDAYS[day.weekday()]} {day.day} de {MONTHS[day.month - 1]}"
