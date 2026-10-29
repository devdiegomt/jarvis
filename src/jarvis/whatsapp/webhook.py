"""Servidor que recibe los avisos (webhooks) de WhatsApp enviados por Meta.

- GET /webhook: verificación inicial de Meta (hub.challenge).
- POST /webhook: mensajes entrantes. Se verifica la firma, se responde 200 de inmediato y el
  mensaje se entrega al worker, que lo procesa en segundo plano.
"""

import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

WEBHOOK_PATH = "/webhook"
MAX_BODY_BYTES = 1_000_000

logger = logging.getLogger("jarvis.whatsapp")


@dataclass(frozen=True)
class IncomingMessage:
    id: str
    sender: str  # número de quien escribe, solo dígitos
    text: str | None  # None si no es un mensaje de texto (audio, imagen…)


def is_valid_signature(app_secret: str, body: bytes, signature_header: str | None) -> bool:
    """Comprueba la cabecera `X-Hub-Signature-256` (HMAC-SHA256 del cuerpo con el App Secret)."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.removeprefix("sha256="))


def extract_messages(payload: dict[str, Any], phone_number_id: str) -> list[IncomingMessage]:
    """Mensajes del aviso dirigidos a nuestro número. Ignora estados (entregado, leído…)."""
    messages: list[IncomingMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if change.get("field") != "messages":
                continue
            if value.get("metadata", {}).get("phone_number_id") != phone_number_id:
                continue
            for message in value.get("messages", []):
                if not message.get("id") or not message.get("from"):
                    continue
                text = message.get("text", {}).get("body") if message.get("type") == "text" else None
                messages.append(IncomingMessage(id=message["id"], sender=message["from"], text=text))
    return messages


@dataclass(frozen=True)
class WebhookConfig:
    verify_token: str
    app_secret: str
    phone_number_id: str
    owner_number: str
    # Devuelve False si el mensaje ya se había recibido (Meta reenvía avisos).
    mark_processed: Callable[[str], bool]
    deliver: Callable[[IncomingMessage], None]


def build_server(host: str, port: int, config: WebhookConfig) -> ThreadingHTTPServer:
    handler = type("WebhookHandler", (_WebhookHandler,), {"config": config})
    return ThreadingHTTPServer((host, port), handler)


class _WebhookHandler(BaseHTTPRequestHandler):
    config: WebhookConfig

    def do_GET(self) -> None:  # noqa: N802 - nombre impuesto por http.server
        url = urlparse(self.path)
        if url.path == "/":
            self._respond(HTTPStatus.OK, "JARVIS está escuchando.")
            return
        if url.path != WEBHOOK_PATH:
            self._respond(HTTPStatus.NOT_FOUND, "")
            return
        params = {key: values[0] for key, values in parse_qs(url.query).items()}
        if params.get("hub.mode") == "subscribe" and hmac.compare_digest(
            params.get("hub.verify_token", ""), self.config.verify_token
        ):
            logger.info("Webhook verificado por Meta.")
            self._respond(HTTPStatus.OK, params.get("hub.challenge", ""))
        else:
            logger.warning("Verificación de webhook rechazada (token incorrecto).")
            self._respond(HTTPStatus.FORBIDDEN, "")

    def do_POST(self) -> None:  # noqa: N802 - nombre impuesto por http.server
        if urlparse(self.path).path != WEBHOOK_PATH:
            self._respond(HTTPStatus.NOT_FOUND, "")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            self._respond(HTTPStatus.BAD_REQUEST, "")
            return
        body = self.rfile.read(length)
        if not is_valid_signature(self.config.app_secret, body, self.headers.get("X-Hub-Signature-256")):
            logger.warning("Aviso rechazado: firma inválida.")
            self._respond(HTTPStatus.UNAUTHORIZED, "")
            return
        try:
            payload = json.loads(body)
        except ValueError:
            self._respond(HTTPStatus.BAD_REQUEST, "")
            return

        # Respondemos a Meta antes de procesar: el agente puede tardar varios segundos.
        self._respond(HTTPStatus.OK, "")
        for message in extract_messages(payload, self.config.phone_number_id):
            self._route(message)

    def _route(self, message: IncomingMessage) -> None:
        if message.sender != self.config.owner_number:
            logger.warning("Mensaje ignorado de un número no autorizado (termina en %s).", message.sender[-4:])
            return
        if not self.config.mark_processed(message.id):
            logger.info("Mensaje %s duplicado; ignorado.", message.id)
            return
        logger.info("Mensaje %s recibido.", message.id)
        self.config.deliver(message)

    def _respond(self, status: HTTPStatus, text: str) -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Silencia el log por defecto de http.server (incluye rutas y parámetros)."""
