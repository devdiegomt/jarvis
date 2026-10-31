"""Lectura de Gmail (permiso gmail.readonly): buscar y leer correos. Nunca envía, borra ni marca nada.

El contenido de los correos es externo: quien lo usa lo trata como información, nunca como
instrucciones.
"""

import base64
import html
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, tzinfo
from email.utils import parseaddr
from pathlib import Path
from typing import Any

import httplib2
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from jarvis.google_auth import (
    GMAIL_READ_SCOPE,
    LOGIN_HINT,
    GoogleAuthError,
    GoogleNotAuthorizedError,
    load_credentials,
)

MAX_BODY_CHARS = 6000

# Devuelve un cliente de la Gmail API v1 (o un doble en los tests).
ServiceFactory = Callable[[], Any]


class MailError(Exception):
    """Fallo al leer el correo. El mensaje está pensado para el usuario."""


class MailNotAuthorizedError(MailError):
    """Falta autorizar la lectura del correo."""


@dataclass(frozen=True)
class Email:
    id: str
    sender_name: str
    sender_email: str
    subject: str
    snippet: str
    received_at: datetime


def gmail_read_service_factory(token_file: Path) -> ServiceFactory:
    def factory() -> Any:
        credentials = load_credentials(token_file, [GMAIL_READ_SCOPE])
        return build("gmail", "v1", credentials=credentials, cache_discovery=False)

    return factory


class GmailReader:
    def __init__(self, service_factory: ServiceFactory, timezone: tzinfo) -> None:
        self._service_factory = service_factory
        self._service: Any = None
        self._tz = timezone

    def search(self, query: str, max_results: int = 10) -> list[Email]:
        """Correos que cumplen una búsqueda de Gmail, del más reciente al más antiguo."""
        response = self._call(lambda users: users.messages().list(userId="me", q=query, maxResults=max_results))
        return [self._metadata(item["id"]) for item in response.get("messages", [])]

    def read(self, message_id: str) -> tuple[Email, str]:
        """Un correo y su texto (recortado)."""
        message = self._call(lambda users: users.messages().get(userId="me", id=message_id, format="full"))
        body = _plain_text(message.get("payload", {}))
        if len(body) > MAX_BODY_CHARS:
            body = body[:MAX_BODY_CHARS] + "\n[…recortado]"
        return self._to_email(message), body

    def _metadata(self, message_id: str) -> Email:
        message = self._call(
            lambda users: users.messages().get(
                userId="me", id=message_id, format="metadata", metadataHeaders=["From", "Subject"]
            )
        )
        return self._to_email(message)

    def _to_email(self, message: dict[str, Any]) -> Email:
        headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
        name, address = parseaddr(headers.get("from", ""))
        received = datetime.fromtimestamp(int(message.get("internalDate", "0")) / 1000, self._tz)
        return Email(
            id=str(message["id"]),
            sender_name=name or address,
            sender_email=address.lower(),
            subject=headers.get("subject", "").strip() or "(sin asunto)",
            snippet=html.unescape(message.get("snippet", "")).strip(),
            received_at=received,
        )

    def _call(self, request: Callable[[Any], Any]) -> Any:
        try:
            if self._service is None:
                self._service = self._service_factory()
            return request(self._service.users()).execute()
        except HttpError as exc:
            status = exc.resp.status
            if status in (401, 403):
                raise MailNotAuthorizedError(f"Falta el permiso para leer tu correo. {LOGIN_HINT}") from exc
            if status == 404:
                raise MailError("No encontré ese correo.") from exc
            raise MailError(f"Gmail respondió con un error ({status}).") from exc
        except GoogleNotAuthorizedError as exc:
            raise MailNotAuthorizedError(str(exc)) from exc
        except GoogleAuthError as exc:
            raise MailError(str(exc)) from exc
        except RefreshError as exc:
            raise MailNotAuthorizedError(f"Google rechazó la autorización. {LOGIN_HINT}") from exc
        except (TransportError, httplib2.HttpLib2Error, OSError) as exc:
            raise MailError("No pude conectar con Gmail.") from exc


def _plain_text(payload: dict[str, Any]) -> str:
    """Texto del correo: la parte text/plain, o el HTML sin etiquetas si no hay."""
    plain, rich = _find_part(payload, "text/plain"), _find_part(payload, "text/html")
    if plain:
        return plain.strip()
    if rich:
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", rich)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", html.unescape(text)).strip()
    return ""


def _find_part(payload: dict[str, Any], mime: str) -> str:
    if payload.get("mimeType") == mime and payload.get("body", {}).get("data"):
        data = payload["body"]["data"]
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        found = _find_part(part, mime)
        if found:
            return found
    return ""


def watched_query(patterns: list[str], after: datetime | None = None) -> str:
    """Búsqueda de Gmail para los correos recibidos de los contactos vigilados."""
    senders = " OR ".join(p.lstrip("@") for p in patterns)
    query = f"from:({senders}) -in:sent -in:chats"
    if after is not None:
        query += f" after:{int(after.timestamp())}"
    return query
