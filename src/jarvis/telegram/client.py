"""Cliente mínimo de la API de bots de Telegram (https://core.telegram.org/bots/api)."""

import base64
import http.client
import json
import logging
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from functools import cache
from typing import Any

import truststore

from jarvis.chat import ChannelError

API_URL = "https://api.telegram.org"
POLL_TIMEOUT_SECONDS = 30  # long polling: Telegram mantiene la consulta abierta hasta 30 s
REQUEST_MARGIN_SECONDS = 15
DOWNLOAD_TIMEOUT_SECONDS = 60
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # límite de descarga de la API de bots

# Llama a un método de la API y devuelve el JSON de respuesta (reemplazable en los tests).
Caller = Callable[[str, dict[str, Any], float], dict[str, Any]]
# Descarga un archivo (URL, tiempo máximo, tamaño máximo) y devuelve sus bytes (reemplazable en los tests).
Downloader = Callable[[str, float, int], bytes]
# Sube un archivo: (URL, campos, (campo, nombre, tipo, contenido), tiempo máximo) → JSON de respuesta.
Uploader = Callable[[str, dict[str, str], tuple[str, str, str, bytes], float], dict[str, Any]]
UPLOAD_TIMEOUT_SECONDS = 60
MAX_IDLE_SECONDS = 30  # más inactiva que esto, se abre una conexión nueva antes de usarla

logger = logging.getLogger("jarvis.chat")


class TelegramError(ChannelError):
    """Error de la API de Telegram. El mensaje está pensado para el usuario."""


class TelegramConnectionError(TelegramError):
    """Fallo temporal de red: se puede reintentar."""


class TelegramAuthError(TelegramError):
    """Token inválido o revocado: reintentar no sirve."""


class TelegramCertificateError(TelegramError):
    """El certificado HTTPS no es de confianza: reintentar no sirve."""


class TelegramConflictError(TelegramError):
    """Otra instancia está leyendo los mensajes del mismo bot."""


class TelegramClient:
    def __init__(
        self,
        bot_token: str,
        call: Caller | None = None,
        download: Downloader | None = None,
        upload: Uploader | None = None,
    ) -> None:
        self._base_url = f"{API_URL}/bot{bot_token}"
        self._file_url = f"{API_URL}/file/bot{bot_token}"
        self._call = call or http_call
        self._download = download or http_download
        self._upload = upload or http_upload

    def get_me(self) -> dict[str, Any]:
        return self._request("getMe", {})

    def delete_webhook(self) -> None:
        """El long polling no funciona si el bot tiene un webhook configurado."""
        self._request("deleteWebhook", {"drop_pending_updates": False})

    def set_commands(self, commands: dict[str, str]) -> None:
        payload = [{"command": name, "description": text} for name, text in commands.items()]
        self._request("setMyCommands", {"commands": payload})

    def get_updates(self, offset: int | None, timeout: int = POLL_TIMEOUT_SECONDS) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        return self._request("getUpdates", params, timeout=timeout + REQUEST_MARGIN_SECONDS)

    def send_message(
        self, chat_id: str, text: str, buttons: list[tuple[str, str]] | None = None
    ) -> dict[str, Any]:
        """Envía texto plano. `buttons` son pares (texto, dato) que se muestran en una fila."""
        params: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if buttons:
            params["reply_markup"] = {
                "inline_keyboard": [[{"text": label, "callback_data": data} for label, data in buttons]]
            }
        return self._request("sendMessage", params)

    def edit_message_text(self, chat_id: str, message_id: int, text: str) -> None:
        """Reemplaza el texto de un mensaje y quita sus botones."""
        self._request("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text})

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        """Confirma a Telegram que se recibió el clic en un botón (si no, el botón queda "cargando")."""
        self._request("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def send_typing(self, chat_id: str) -> None:
        self._request("sendChatAction", {"chat_id": chat_id, "action": "typing"})

    def send_voice(self, chat_id: str, audio: bytes) -> dict[str, Any]:
        """Envía una nota de voz (OGG/Opus)."""
        file = ("voice", "respuesta.ogg", "audio/ogg", audio)
        response = self._upload(f"{self._base_url}/sendVoice", {"chat_id": chat_id}, file, UPLOAD_TIMEOUT_SECONDS)
        return _result(response)

    def download_file(self, file_id: str) -> bytes:
        """Descarga un archivo enviado al bot (por ejemplo, una nota de voz) a memoria."""
        info = self._request("getFile", {"file_id": file_id})
        if int(info.get("file_size") or 0) > MAX_DOWNLOAD_BYTES:
            raise TelegramError("El archivo es demasiado grande para descargarlo (máximo 20 MB).")
        if "file_path" not in info:
            raise TelegramError("Telegram no permitió descargar el archivo.")
        url = f"{self._file_url}/{info['file_path']}"
        return self._download(url, DOWNLOAD_TIMEOUT_SECONDS, MAX_DOWNLOAD_BYTES)

    def _request(self, method: str, params: dict[str, Any], timeout: float = REQUEST_MARGIN_SECONDS) -> Any:
        return _result(self._call(f"{self._base_url}/{method}", params, timeout))


def _result(response: dict[str, Any]) -> Any:
    if not response.get("ok"):
        raise _api_error(response.get("error_code"), response.get("description", ""))
    return response.get("result")


def http_call(url: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
    """POST con JSON. Los errores nunca incluyen la URL, porque contiene el token del bot."""
    body = json.dumps(params).encode("utf-8")
    return _post_json(url, body, {"Content-Type": "application/json"}, timeout)


def http_upload(
    url: str, fields: dict[str, str], file: tuple[str, str, str, bytes], timeout: float
) -> dict[str, Any]:
    """POST multipart/form-data con un archivo. Como `http_call`, los errores no incluyen la URL."""
    boundary = uuid.uuid4().hex
    field_name, filename, content_type, content = file
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in fields.items()
    ]
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode()
        + content
        + f"\r\n--{boundary}--\r\n".encode()
    )
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    return _post_json(url, b"".join(parts), headers, timeout)


def _post_json(url: str, body: bytes, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    status, data = _request_or_explain("POST", url, body, headers, timeout)
    try:
        # Telegram responde también los errores con JSON {"ok": false, "error_code": ..., "description": ...}.
        return json.loads(data)
    except ValueError:
        raise _api_error(status, "") from None


def http_download(url: str, timeout: float, max_bytes: int) -> bytes:
    """GET de un archivo. Como en `http_call`, los errores nunca incluyen la URL (lleva el token)."""
    status, data = _request_or_explain("GET", url, None, {}, timeout, max_bytes=max_bytes)
    if status == 429 or status >= 500:
        raise _api_error(status, "")
    if status >= 400:
        raise TelegramError(f"Telegram no entregó el archivo ({status}).")
    if len(data) > max_bytes:
        raise TelegramError("El archivo es demasiado grande para descargarlo (máximo 20 MB).")
    return data


def _request_or_explain(
    method: str,
    url: str,
    body: bytes | None,
    headers: dict[str, str],
    timeout: float,
    max_bytes: int | None = None,
) -> tuple[int, bytes]:
    try:
        return POOL.request(method, url, body, headers, timeout, max_bytes=max_bytes)
    except (OSError, http.client.HTTPException) as exc:  # OSError incluye TimeoutError y errores de TLS
        raise _network_error(exc) from None


class ConnectionPool:
    """Conexiones HTTPS que se mantienen abiertas y se reutilizan (una por hilo y servidor).

    Abrir una conexión (TCP + saludo TLS) cuesta medio segundo o más por llamada; reutilizarla
    ahorra ese tiempo en cada mensaje. Cada hilo tiene la suya, así la espera de mensajes nuevos
    (long polling) no bloquea las respuestas ni los avisos.
    """

    def __init__(
        self,
        connect: Callable[[str, float], http.client.HTTPConnection] | None = None,
        clock: Callable[[], float] = time.monotonic,
        max_idle: float = MAX_IDLE_SECONDS,
    ) -> None:
        self._connect = connect or open_https_connection
        self._clock = clock
        self._max_idle = max_idle
        self._local = threading.local()

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: dict[str, str],
        timeout: float,
        max_bytes: int | None = None,
    ) -> tuple[int, bytes]:
        """Hace la petición y devuelve (código HTTP, cuerpo). Los fallos de red se propagan tal cual."""
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        label = _label(parts.path)
        while True:
            conn, reused = self._connection(host, timeout)
            started = self._clock()
            try:
                conn.request(method, path, body=body, headers=headers)
                response = conn.getresponse()
                data = response.read() if max_bytes is None else response.read(max_bytes + 1)
            except _STALE_ERRORS:
                self._close(host)
                if reused:  # el servidor cerró la conexión inactiva antes de recibir el pedido
                    continue
                raise
            except BaseException:
                self._close(host)
                raise
            if response.will_close or not response.isclosed():  # cerrada por el servidor o sin leer completa
                self._close(host)
            else:
                self._connections()[host] = (conn, self._clock())
            if label != "getUpdates":  # la espera de mensajes dura hasta 30 s: no es lentitud
                elapsed = self._clock() - started
                kind = "reutilizada" if reused else "nueva"
                logger.info("Telegram %s en %.2f s (conexión %s).", label, elapsed, kind)
            return response.status, data

    def close_all(self) -> None:
        """Cierra las conexiones del hilo actual."""
        for host in list(self._connections()):
            self._close(host)

    def _connection(self, host: str, timeout: float) -> tuple[http.client.HTTPConnection, bool]:
        connections = self._connections()
        current = connections.get(host)
        if current is not None:
            conn, last_used = current
            if self._clock() - last_used <= self._max_idle:
                conn.timeout = timeout
                if conn.sock is not None:
                    conn.sock.settimeout(timeout)
                return conn, True
            self._close(host)  # inactiva hace rato: el servidor probablemente ya la cerró
        conn = self._connect(host, timeout)
        connections[host] = (conn, self._clock())
        return conn, False

    def _close(self, host: str) -> None:
        current = self._connections().pop(host, None)
        if current is not None:
            current[0].close()

    def _connections(self) -> dict[str, tuple[http.client.HTTPConnection, float]]:
        if not hasattr(self._local, "connections"):
            self._local.connections = {}
        return self._local.connections


# La conexión inactiva se cerró del lado del servidor: se reintenta una vez con una nueva, sin
# riesgo de duplicar un mensaje porque Telegram no llegó a recibirlo. Un tiempo agotado no entra aquí.
_STALE_ERRORS = (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


def _label(path: str) -> str:
    """El método de la API para el registro (sin el token, que va antes en la ruta)."""
    return "descarga" if path.startswith("/file/") else path.rsplit("/", 1)[-1]


def open_https_connection(host: str, timeout: float) -> http.client.HTTPConnection:
    """Conexión HTTPS verificada con el almacén del sistema; respeta el proxy del sistema, si hay."""
    proxy = urllib.request.getproxies().get("https")
    if proxy and not urllib.request.proxy_bypass(host):
        target = urllib.parse.urlsplit(proxy if "://" in proxy else f"http://{proxy}")
        conn = http.client.HTTPSConnection(
            target.hostname or "", target.port or 8080, timeout=timeout, context=_ssl_context()
        )
        headers = {}
        if target.username:
            credentials = f"{urllib.parse.unquote(target.username)}:{urllib.parse.unquote(target.password or '')}"
            headers["Proxy-Authorization"] = "Basic " + base64.b64encode(credentials.encode()).decode()
        conn.set_tunnel(host, 443, headers=headers)
        return conn
    return http.client.HTTPSConnection(host, timeout=timeout, context=_ssl_context())


POOL = ConnectionPool()


@cache
def _ssl_context() -> ssl.SSLContext:
    """Verifica HTTPS con el almacén de certificados del sistema operativo (como el navegador).

    Así funciona también cuando un antivirus o un proxy de confianza inspecciona el tráfico
    con su propio certificado raíz instalado en el sistema. La verificación nunca se desactiva.
    """
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _network_error(reason: object) -> TelegramError:
    """Explica la causa de un fallo de red, sin incluir la URL (contiene el token)."""
    if isinstance(reason, ssl.SSLCertVerificationError):
        return TelegramCertificateError(
            "No pude conectar con Telegram: su certificado HTTPS no es de confianza en este equipo. "
            "Suele deberse a un antivirus o proxy que inspecciona las conexiones (ver README)."
        )
    if isinstance(reason, socket.gaierror):
        return TelegramConnectionError(
            "No pude conectar con Telegram: no se encontró api.telegram.org (revisa tu conexión)."
        )
    if isinstance(reason, TimeoutError):
        return TelegramConnectionError("No pude conectar con Telegram: se agotó el tiempo de espera.")
    return TelegramConnectionError(f"No pude conectar con Telegram ({type(reason).__name__}).")


def _api_error(code: int | None, description: str) -> TelegramError:
    if code in (401, 404):
        return TelegramAuthError("El token del bot no es válido o fue revocado (TELEGRAM_BOT_TOKEN).")
    if code == 409:
        return TelegramConflictError(
            "Otra copia de JARVIS (u otro programa) está usando este bot. Ciérrala y vuelve a intentar."
        )
    if code == 429 or (code is not None and code >= 500):
        return TelegramConnectionError(f"Telegram no está disponible en este momento ({code}).")
    return TelegramError(f"Telegram rechazó la petición ({code}). {description}".strip())
