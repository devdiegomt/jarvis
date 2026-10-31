"""Búsqueda en internet y lectura de enlaces, con las tools de Anthropic (se ejecutan en sus servidores).

No hay función propia: se declaran en la petición y el modelo las usa dentro de su respuesta.
Son de solo lectura, así que no piden confirmación. Cada búsqueda se paga aparte, por eso hay un
máximo por mensaje.
"""

from datetime import tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.config import WebSettings

MAX_FETCHES = 3  # enlaces que se pueden leer por mensaje
MAX_FETCH_TOKENS = 20_000  # tope aproximado de texto leído por página


def build_server_tools(settings: WebSettings, timezone: tzinfo | None = None) -> list[dict[str, Any]]:
    """Definiciones de `web_search` y `web_fetch`, o ninguna si la búsqueda está desactivada."""
    if not settings.enabled:
        return []
    search: dict[str, Any] = {
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": settings.max_searches,
    }
    location = _user_location(settings, timezone)
    if location:
        search["user_location"] = location
    fetch = {
        "type": "web_fetch_20260209",
        "name": "web_fetch",
        "max_uses": MAX_FETCHES,
        "max_content_tokens": MAX_FETCH_TOKENS,
        "citations": {"enabled": True},
    }
    return [search, fetch]


def _user_location(settings: WebSettings, timezone: tzinfo | None) -> dict[str, str] | None:
    """Ubicación aproximada para que el clima o "cerca de mí" den resultados locales."""
    location = {"type": "approximate"}
    if settings.city:
        location["city"] = settings.city
    if settings.country:
        location["country"] = settings.country
    if isinstance(timezone, ZoneInfo):
        location["timezone"] = timezone.key
    return location if len(location) > 1 else None
