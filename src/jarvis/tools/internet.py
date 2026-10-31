"""Búsqueda en internet y lectura de enlaces, con las tools de Anthropic (se ejecutan en sus servidores).

No hay función propia: se declaran en la petición y el modelo las usa dentro de su respuesta.
Son de solo lectura, así que no piden confirmación. Cada búsqueda se paga aparte, por eso hay un
máximo por mensaje.
"""

from typing import Any

from jarvis.config import WebSettings

MAX_FETCHES = 3  # enlaces que se pueden leer por mensaje
MAX_FETCH_TOKENS = 20_000  # tope aproximado de texto leído por página


def build_server_tools(settings: WebSettings) -> list[dict[str, Any]]:
    """Definiciones de `web_search` y `web_fetch`, o ninguna si la búsqueda está desactivada.

    La ubicación del usuario no va en `user_location`: la API rechaza la petición entera con países
    que no admite (por ejemplo, CO). Va en el system prompt, y el modelo la usa en sus búsquedas.
    """
    if not settings.enabled:
        return []
    search: dict[str, Any] = {
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": settings.max_searches,
    }
    fetch = {
        "type": "web_fetch_20260209",
        "name": "web_fetch",
        "max_uses": MAX_FETCHES,
        "max_content_tokens": MAX_FETCH_TOKENS,
        "citations": {"enabled": True},
    }
    return [search, fetch]
