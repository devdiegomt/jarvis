"""Servidor HTTP de la API (librería estándar). Solo escucha en el propio PC.

Rutas:
- `GET /` y archivos de la app web (PWA), sin clave: son solo la interfaz.
- `GET /api/salud`, sin clave: para comprobar la conexión (no dice nada más).
- `GET /api/hoy`, `/api/pendientes`, `/api/recordatorios`, `/api/clima`, `/api/gasto`: sin IA.
- `POST /api/chat` `{"texto": "..."}` y `POST /api/boton` `{"dato": "..."}`: el chat con JARVIS.

Las rutas `/api/*` (menos `salud`) piden `Authorization: Bearer <clave>`. El registro anota solo el
método, la ruta, el código y el tiempo; nunca el contenido.
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any

from jarvis.api.auth import KeyChecker
from jarvis.api.channel import BusyError, ChatBridge
from jarvis.api.icons import icon_png

LOCAL_HOSTS = ("127.0.0.1", "::1")
MAX_BODY_BYTES = 16 * 1024
MAX_TEXT_CHARS = 4000
READ_TIMEOUT_SECONDS = 30
QUICK_ROUTES = {
    "/api/pendientes": "/pendientes",
    "/api/recordatorios": "/recordatorios",
    "/api/clima": "/clima",
    "/api/gasto": "/gasto",
}
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
}
ICONS = {"/icon-180.png": 180, "/icon-192.png": 192, "/icon-512.png": 512}
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
LOCKED_TEXT = "Demasiados intentos con una clave equivocada. Espera un minuto."
TOO_LONG_TEXT = f"El mensaje es muy largo (máximo {MAX_TEXT_CHARS} caracteres)."
TAILSCALE_USER_HEADER = "Tailscale-User-Login"  # lo agrega `tailscale serve` a cada pedido de la red

logger = logging.getLogger("jarvis.chat")


class ApiServer:
    def __init__(
        self,
        *,
        port: int,
        checker: KeyChecker,
        bridge: ChatBridge,
        quick_commands: dict[str, Callable[[], str]],
        today: Callable[[], dict[str, Any]],
        tailscale_user: str = "",
        host: str = "127.0.0.1",
    ) -> None:
        if host not in LOCAL_HOSTS:
            raise ValueError("La API solo escucha en el propio PC (127.0.0.1); se publica con tailscale serve.")
        self._routes = _Routes(checker, bridge, quick_commands, today, tailscale_user.lower())
        self._server = ThreadingHTTPServer((host, port), self._handler_class())
        self._server.daemon_threads = True

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._server.serve_forever, name="jarvis-api", daemon=True)
        thread.start()
        return thread

    def serve_forever(self) -> None:
        self._server.serve_forever()

    def shutdown(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        routes = self._routes

        class Handler(BaseHTTPRequestHandler):
            timeout = READ_TIMEOUT_SECONDS
            server_version = "JARVIS"
            sys_version = ""

            def do_GET(self) -> None:  # noqa: N802 - nombre que exige http.server
                routes.handle(self, "GET")

            def do_POST(self) -> None:  # noqa: N802
                routes.handle(self, "POST")

            def do_PUT(self) -> None:  # noqa: N802
                routes.reply(self, 405, {"error": "Método no permitido."})

            # Sin CORS (OPTIONS rechazado): el navegador no deja que otro sitio web use la API.
            do_DELETE = do_PATCH = do_OPTIONS = do_PUT  # noqa: N815

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                pass  # el registro propio no incluye la dirección ni el contenido

        return Handler


class _Routes:
    def __init__(
        self,
        checker: KeyChecker,
        bridge: ChatBridge,
        quick_commands: dict[str, Callable[[], str]],
        today: Callable[[], dict[str, Any]],
        tailscale_user: str,
    ) -> None:
        self._checker = checker
        self._bridge = bridge
        self._quick = quick_commands
        self._today = today
        self._tailscale_user = tailscale_user

    def handle(self, request: BaseHTTPRequestHandler, method: str) -> None:
        started = time.monotonic()
        path = request.path.split("?", 1)[0]
        try:
            status = self._dispatch(request, method, path)
        except Exception:
            logger.exception("Error inesperado en la API (%s %s).", method, path)
            status = self.reply(request, 500, {"error": "Algo salió mal en JARVIS. Inténtalo de nuevo."})
        if path.startswith("/api/"):
            logger.info("App: %s %s → %d (%.2f s).", method, path, status, time.monotonic() - started)

    def _dispatch(self, request: BaseHTTPRequestHandler, method: str, path: str) -> int:
        if method == "GET" and path in STATIC_FILES:
            name, content_type = STATIC_FILES[path]
            return self.send(request, 200, _static(name), content_type, cache="no-cache")
        if method == "GET" and path in ICONS:
            return self.send(request, 200, icon_png(ICONS[path]), "image/png", cache="max-age=86400")
        if path == "/api/salud" and method == "GET":
            return self.reply(request, 200, {"ok": True})
        if not path.startswith("/api/"):
            return self.reply(request, 404, {"error": "No encontrado."})

        denied = self._authorize(request)
        if denied is not None:
            return denied
        if method == "GET" and path == "/api/hoy":
            return self.reply(request, 200, self._today())
        if method == "GET" and path in QUICK_ROUTES:
            return self.reply(request, 200, {"texto": self._quick[QUICK_ROUTES[path]]()})
        if method == "POST" and path in ("/api/chat", "/api/boton"):
            return self._chat(request, path)
        return self.reply(request, 404, {"error": "No encontrado."})

    def _authorize(self, request: BaseHTTPRequestHandler) -> int | None:
        if self._checker.locked():
            return self.reply(request, 429, {"error": LOCKED_TEXT})
        if self._tailscale_user:
            login = (request.headers.get(TAILSCALE_USER_HEADER) or "").strip().lower()
            if login != self._tailscale_user:
                return self.reply(request, 403, {"error": "Esta cuenta de Tailscale no tiene acceso a JARVIS."})
        header = request.headers.get("Authorization") or ""
        key = header[7:].strip() if header.lower().startswith("bearer ") else None
        if not self._checker.check(key):
            return self.reply(request, 401, {"error": "Clave incorrecta. Genera una con «jarvis api-clave»."})
        return None

    def _chat(self, request: BaseHTTPRequestHandler, path: str) -> int:
        body, problem = _read_json(request)
        if problem is not None:
            return self.reply(request, 400, {"error": problem})
        field = "texto" if path == "/api/chat" else "dato"
        value = body.get(field) if isinstance(body, dict) else None
        if not isinstance(value, str) or not value.strip():
            return self.reply(request, 400, {"error": f"Falta «{field}»."})
        if len(value) > MAX_TEXT_CHARS:
            return self.reply(request, 413, {"error": TOO_LONG_TEXT})
        try:
            reply = self._bridge.send_text(value) if field == "texto" else self._bridge.press_button(value)
        except BusyError as exc:
            return self.reply(request, 503, {"error": str(exc)})
        return self.reply(request, 200, reply.to_dict())

    def reply(self, request: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> int:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self.send(request, status, body, "application/json; charset=utf-8", cache="no-store")

    def send(
        self, request: BaseHTTPRequestHandler, status: int, body: bytes, content_type: str, cache: str
    ) -> int:
        request.send_response(status)
        request.send_header("Content-Type", content_type)
        request.send_header("Content-Length", str(len(body)))
        request.send_header("Cache-Control", cache)
        for name, value in SECURITY_HEADERS.items():
            request.send_header(name, value)
        request.end_headers()
        request.wfile.write(body)
        return status


def _read_json(request: BaseHTTPRequestHandler) -> tuple[Any, str | None]:
    if not (request.headers.get("Content-Type") or "").lower().startswith("application/json"):
        return None, "El cuerpo debe ser JSON (Content-Type: application/json)."
    try:
        length = int(request.headers.get("Content-Length") or "0")
    except ValueError:
        length = -1
    if not 0 < length <= MAX_BODY_BYTES:
        return None, f"El cuerpo debe tener entre 1 y {MAX_BODY_BYTES} bytes."
    try:
        return json.loads(request.rfile.read(length)), None
    except (ValueError, UnicodeDecodeError):
        return None, "El cuerpo no es un JSON válido."


def _static(name: str) -> bytes:
    return resources.files("jarvis.api").joinpath("static", name).read_bytes()
