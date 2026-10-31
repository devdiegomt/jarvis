"""Autorización OAuth de escritorio con Google (Calendar y Gmail)."""

import json
import os
import webbrowser
from collections.abc import Sequence
from pathlib import Path

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Permisos mínimos: ver y editar eventos del calendario (no compartir ni borrar calendarios) y
# enviar correos (no leerlos ni borrarlos). `calendar.readonly` es el permiso de antes de la v0.12:
# con él JARVIS sigue leyendo el calendario, pero no puede agendar.
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
# Leer correos (para los avisos de clientes): no permite enviar, borrar ni modificar nada.
GMAIL_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

SCOPE_DESCRIPTIONS = {
    CALENDAR_EVENTS_SCOPE: (
        "ver y editar los eventos de tu calendario (siempre te pedirá confirmación antes de cambiar algo)"
    ),
    CALENDAR_SCOPE: "leer tu calendario",
    GMAIL_READ_SCOPE: "leer tus correos (sin enviar, borrar ni modificar nada; para avisarte de tus clientes)",
    GMAIL_SEND_SCOPE: "enviar correos en tu nombre (JARVIS solo te envía el resumen diario)",
}

LOGIN_HINT = "Ejecuta `uv run jarvis google-login` para autorizar el acceso."


class GoogleAuthError(Exception):
    """Fallo de autorización con Google. El mensaje está pensado para el usuario."""


class GoogleNotAuthorizedError(GoogleAuthError):
    """No hay autorización válida, o le faltan permisos."""


def token_scopes(token_file: Path) -> list[str]:
    """Permisos guardados en el token (sin conectarse a Google). Vacío si no hay token válido."""
    try:
        scopes = json.loads(token_file.read_text(encoding="utf-8")).get("scopes", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [str(scope) for scope in scopes] if isinstance(scopes, list) else []


def load_credentials(token_file: Path, required_scopes: Sequence[str]) -> Credentials:
    """Carga el token guardado, comprueba sus permisos y lo renueva si venció."""
    if not token_file.exists():
        raise GoogleNotAuthorizedError(f"Google no está autorizado. {LOGIN_HINT}")
    try:
        # Sin pasar `scopes`: se usan los permisos guardados en el token.
        credentials = Credentials.from_authorized_user_file(str(token_file))
    except ValueError as exc:
        raise GoogleNotAuthorizedError(f"El token de Google es inválido. {LOGIN_HINT}") from exc

    missing = [scope for scope in required_scopes if scope not in (credentials.scopes or [])]
    if missing:
        raise GoogleNotAuthorizedError(
            f"La autorización de Google no incluye el permiso para {describe_scopes(missing)}. "
            f"{LOGIN_HINT}"
        )

    if credentials.valid:
        return credentials
    if not credentials.refresh_token:
        raise GoogleNotAuthorizedError(f"La autorización de Google venció. {LOGIN_HINT}")

    try:
        credentials.refresh(Request())
    except RefreshError as exc:
        raise GoogleNotAuthorizedError(
            f"Google rechazó la autorización (pudo ser revocada o caducar). {LOGIN_HINT}"
        ) from exc
    except TransportError as exc:
        raise GoogleAuthError("No pude conectar con Google para renovar la autorización.") from exc
    save_credentials(credentials, token_file)
    return credentials


def login(credentials_file: Path, token_file: Path, scopes: Sequence[str]) -> None:
    """Abre el navegador para que el usuario autorice los permisos y guarda el token."""
    if not credentials_file.exists():
        raise GoogleAuthError(
            f"No encuentro el archivo de credenciales OAuth en {credentials_file}. "
            "Descárgalo desde Google Cloud Console (ver README) o define GOOGLE_CREDENTIALS_FILE."
        )
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), list(scopes))
    except ValueError as exc:
        raise GoogleAuthError(
            f"{credentials_file} no es un archivo de credenciales OAuth válido. "
            "Debe ser un ID de cliente de tipo 'App de escritorio'."
        ) from exc
    credentials = flow.run_local_server(
        port=0,
        open_browser=_browser_available(),
        authorization_prompt_message="Abre esta URL para autorizar a JARVIS:\n{url}",
        success_message="Listo. Ya puedes cerrar esta ventana y volver a la terminal.",
    )

    # Google permite desmarcar permisos en la pantalla de consentimiento.
    granted = list(credentials.granted_scopes or scopes)
    missing = [scope for scope in scopes if scope not in granted]
    if missing:
        raise GoogleAuthError(
            f"No se concedió el permiso para {describe_scopes(missing)}. "
            "Vuelve a ejecutar el login y marca todas las casillas."
        )
    save_credentials(credentials, token_file, scopes=granted)


def describe_scopes(scopes: Sequence[str]) -> str:
    return " y ".join(SCOPE_DESCRIPTIONS.get(scope, scope) for scope in scopes)


def _browser_available() -> bool:
    """Sin navegador (por ejemplo, por SSH) solo se muestra la URL para abrirla a mano."""
    try:
        webbrowser.get()
    except webbrowser.Error:
        return False
    return True


def save_credentials(
    credentials: Credentials, token_file: Path, scopes: Sequence[str] | None = None
) -> None:
    """Guarda el token con permisos de archivo solo para el usuario actual.

    `scopes` permite guardar los permisos realmente concedidos en lugar de los pedidos.
    """
    data = json.loads(credentials.to_json())
    if scopes is not None:
        data["scopes"] = list(scopes)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        json.dump(data, file)
    token_file.chmod(0o600)
