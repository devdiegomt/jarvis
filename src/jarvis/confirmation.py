"""Interpretación de respuestas de confirmación (s/n), común a todos los canales."""

CONFIRMATION_QUESTION = "¿Confirmas? (s/n)"
_YES = {"s", "si", "sí", "y", "yes"}
_NO = {"n", "no"}


def parse_yes_no(answer: str) -> bool | None:
    """True para sí, False para no, None si la respuesta no es válida."""
    # La puntuación sobra: "¡Sí!" o "No." (como suele transcribirse una nota de voz).
    normalized = answer.strip().lower().strip(" .,;!?¡¿")
    if normalized in _YES:
        return True
    if normalized in _NO:
        return False
    return None
