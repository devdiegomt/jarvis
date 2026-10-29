"""Canal de correo con la API de Gmail (permiso gmail.send: solo enviar)."""

import base64
from collections.abc import Callable
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import httplib2
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from jarvis.google_auth import (
    GMAIL_SEND_SCOPE,
    LOGIN_HINT,
    GoogleAuthError,
    GoogleNotAuthorizedError,
    load_credentials,
)
from jarvis.notify.base import NotificationError, NotificationNotAuthorizedError

# Devuelve un cliente de la Gmail API v1 (o un doble en los tests).
ServiceFactory = Callable[[], Any]


def gmail_service_factory(token_file: Path) -> ServiceFactory:
    def factory() -> Any:
        credentials = load_credentials(token_file, [GMAIL_SEND_SCOPE])
        return build("gmail", "v1", credentials=credentials, cache_discovery=False)

    return factory


def build_raw_message(recipient: str, subject: str, body: str) -> str:
    """Correo de texto plano en UTF-8, codificado como lo espera la API de Gmail."""
    message = EmailMessage()
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


class GmailNotifier:
    name = "Gmail"

    def __init__(self, service_factory: ServiceFactory, recipient: str) -> None:
        self._service_factory = service_factory
        self._recipient = recipient

    def send(self, subject: str, body: str) -> None:
        raw = build_raw_message(self._recipient, subject, body)
        try:
            service = self._service_factory()
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
        except GoogleNotAuthorizedError as exc:
            raise NotificationNotAuthorizedError(str(exc)) from exc
        except GoogleAuthError as exc:
            raise NotificationError(str(exc)) from exc
        except HttpError as exc:
            raise _http_error(exc) from exc
        except RefreshError as exc:
            raise NotificationNotAuthorizedError(
                f"Google rechazó la autorización (pudo ser revocada o caducar). {LOGIN_HINT}"
            ) from exc
        except (TransportError, httplib2.HttpLib2Error, OSError) as exc:
            raise NotificationError("No pude conectar con Gmail.") from exc


def _http_error(exc: HttpError) -> NotificationError:
    status = exc.resp.status
    if status == 401:
        return NotificationNotAuthorizedError(f"La autorización de Google no es válida. {LOGIN_HINT}")
    if status == 403:
        return NotificationNotAuthorizedError(
            "Gmail denegó el envío. Revisa que la Gmail API esté habilitada en tu proyecto de "
            f"Google Cloud y que la autorización incluya el permiso de envío. {LOGIN_HINT}"
        )
    if status == 400:
        return NotificationError("Gmail rechazó el correo. Revisa JARVIS_RESUMEN_DESTINATARIO.")
    return NotificationError(f"Gmail respondió con un error ({status}).")
