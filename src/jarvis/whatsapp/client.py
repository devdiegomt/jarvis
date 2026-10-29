"""Envío de mensajes con la WhatsApp Cloud API de Meta (Graph API)."""

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

GRAPH_URL = "https://graph.facebook.com"
MAX_TEXT_LENGTH = 4096  # límite de WhatsApp por mensaje de texto
REQUEST_TIMEOUT_SECONDS = 15

# Hace un POST con JSON y devuelve la respuesta decodificada (reemplazable en los tests).
Poster = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


class WhatsAppError(Exception):
    """Fallo al hablar con la API de WhatsApp. El mensaje está pensado para el usuario."""


class WhatsAppClient:
    def __init__(
        self, access_token: str, phone_number_id: str, api_version: str, post: Poster | None = None
    ) -> None:
        self._url = f"{GRAPH_URL}/{api_version}/{phone_number_id}/messages"
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        self._post = post or http_post

    def send_text(self, to: str, text: str) -> None:
        """Envía un texto; si supera el límite de WhatsApp, lo divide en varios mensajes."""
        for chunk in split_text(text):
            self._post(
                self._url,
                self._headers,
                {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": to,
                    "type": "text",
                    "text": {"body": chunk, "preview_url": False},
                },
            )

    def mark_read(self, message_id: str, show_typing: bool = True) -> None:
        """Marca el mensaje como leído y, opcionalmente, muestra "escribiendo…"."""
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        if show_typing:
            payload["typing_indicator"] = {"type": "text"}
        self._post(self._url, self._headers, payload)


def split_text(text: str, limit: int = MAX_TEXT_LENGTH) -> list[str]:
    """Divide un texto largo, preferentemente por párrafos o líneas."""
    text = text.strip() or "(sin respuesta)"
    chunks: list[str] = []
    while len(text) > limit:
        cut = next(
            (pos for sep in ("\n\n", "\n", " ") if (pos := text.rfind(sep, 0, limit)) > 0), limit
        )
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    chunks.append(text)
    return chunks


def http_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise WhatsAppError(_describe_http_error(exc.code, exc.read())) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WhatsAppError("No pude conectar con WhatsApp.") from exc


def _describe_http_error(status: int, body: bytes) -> str:
    try:
        error = json.loads(body).get("error", {})
    except ValueError:
        error = {}
    if status == 401 or error.get("code") == 190:
        return "El token de WhatsApp no es válido o caducó (WHATSAPP_ACCESS_TOKEN)."
    if error.get("code") == 131030:
        return "Tu número no está en la lista de destinatarios permitidos del número de prueba."
    detail = error.get("message", "")
    return f"WhatsApp respondió con un error ({status}). {detail}".strip()
