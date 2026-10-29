"""Autorización OAuth de escritorio para leer Google Calendar."""

import os
import webbrowser
from pathlib import Path

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from jarvis.agenda.base import CalendarError, CalendarNotAuthorizedError

# Solo lectura: JARVIS no puede crear, modificar ni borrar eventos.
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

LOGIN_HINT = "Ejecuta `uv run jarvis google-login` para autorizar el acceso."


def load_credentials(token_file: Path) -> Credentials:
    """Carga el token guardado y lo renueva si venció."""
    if not token_file.exists():
        raise CalendarNotAuthorizedError(f"Google Calendar no está autorizado. {LOGIN_HINT}")
    try:
        credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    except ValueError as exc:
        raise CalendarNotAuthorizedError(f"El token de Google es inválido. {LOGIN_HINT}") from exc

    if credentials.valid:
        return credentials
    if not credentials.refresh_token:
        raise CalendarNotAuthorizedError(f"La autorización de Google venció. {LOGIN_HINT}")

    try:
        credentials.refresh(Request())
    except RefreshError as exc:
        raise CalendarNotAuthorizedError(
            f"Google rechazó la autorización (pudo ser revocada). {LOGIN_HINT}"
        ) from exc
    except TransportError as exc:
        raise CalendarError("No pude conectar con Google para renovar la autorización.") from exc
    save_credentials(credentials, token_file)
    return credentials


def login(credentials_file: Path, token_file: Path) -> None:
    """Abre el navegador para que el usuario autorice el acceso y guarda el token."""
    if not credentials_file.exists():
        raise CalendarError(
            f"No encuentro el archivo de credenciales OAuth en {credentials_file}. "
            "Descárgalo desde Google Cloud Console (ver README) o define GOOGLE_CREDENTIALS_FILE."
        )
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
    except ValueError as exc:
        raise CalendarError(
            f"{credentials_file} no es un archivo de credenciales OAuth válido. "
            "Debe ser un ID de cliente de tipo 'App de escritorio'."
        ) from exc
    credentials = flow.run_local_server(
        port=0,
        open_browser=_browser_available(),
        authorization_prompt_message="Abre esta URL para autorizar a JARVIS:\n{url}",
        success_message="Listo. Ya puedes cerrar esta ventana y volver a la terminal.",
    )
    save_credentials(credentials, token_file)


def _browser_available() -> bool:
    """Sin navegador (por ejemplo, por SSH) solo se muestra la URL para abrirla a mano."""
    try:
        webbrowser.get()
    except webbrowser.Error:
        return False
    return True


def save_credentials(credentials: Credentials, token_file: Path) -> None:
    """Guarda el token con permisos solo para el usuario actual."""
    token_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(credentials.to_json())
    token_file.chmod(0o600)
