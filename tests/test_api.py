import http.client
import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from anthropic_fakes import FakeClient, text_response, tool_response
from jarvis.agent import Agent
from jarvis.agenda import SampleCalendar
from jarvis.api import channel as channel_module
from jarvis.api.app import describe_api
from jarvis.api.auth import LOCKOUT_SECONDS, MAX_FAILURES, KeyChecker, generate_key, has_key
from jarvis.api.channel import ApiChannel, BusyError, ChatBridge
from jarvis.api.server import ApiServer
from jarvis.chat import ChatService
from jarvis.config import ApiSettings, ConfigError, load_api_settings
from jarvis.memory import ConversationStore
from jarvis.tools import build_registry

TZ = ZoneInfo("America/Bogota")
NOW = datetime(2026, 11, 2, 8, 0, tzinfo=TZ)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Api:
    """Un servidor real en 127.0.0.1 (puerto libre) con el chat y el agente simulados."""

    def __init__(self, tmp_path: Path, responses: list[Any], tailscale_user: str = "") -> None:
        self.key_file = tmp_path / "api_key.sha256"
        self.key = generate_key(self.key_file)
        self.clock = Clock()
        self.client = FakeClient(responses)
        db = tmp_path / "jarvis.db"

        def agent_factory(history: list, system_prompt: str, confirm):  # type: ignore[no-untyped-def]
            registry = build_registry(SampleCalendar(TZ), confirm=confirm, now=lambda: NOW)
            return Agent(client=self.client, registry=registry, model="m", system_prompt=system_prompt, history=history)  # type: ignore[arg-type]

        channel = ApiChannel()
        quick = {"/gasto": lambda: "💸 Hoy: nada", "/pendientes": lambda: "📝 nada"}
        self.chat = ChatService(
            channel=channel,
            store=ConversationStore(db, now=lambda: NOW),
            agent_factory=agent_factory,
            system_prompt=lambda: "p",
            now=lambda: NOW,
            confirmation_timeout=5,
            quick_commands=quick,
        )
        self.chat.start()
        self.server = ApiServer(
            port=0,
            checker=KeyChecker(self.key_file, clock=self.clock),
            bridge=ChatBridge(channel, self.chat.submit, reply_timeout=5),
            quick_commands=quick,
            today=lambda: {"dia": "lunes 2 de noviembre", "reuniones": []},
            tailscale_user=tailscale_user,
        )
        self.server.start()

    def request(
        self, method: str, path: str, body: Any = None, key: str | None = "default", headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        all_headers = dict(headers or {})
        if key is not None:
            all_headers["Authorization"] = f"Bearer {self.key if key == 'default' else key}"
        payload = None
        if body is not None:
            payload = body if isinstance(body, bytes) else json.dumps(body).encode()
            all_headers.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=payload, headers=all_headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, dict(response.getheaders()), data

    def json(self, method: str, path: str, body: Any = None, **kwargs: Any) -> tuple[int, Any]:
        status, _, data = self.request(method, path, body, **kwargs)
        return status, json.loads(data)


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    server = Api(tmp_path, [])
    yield server
    server.server.shutdown()


# --- Clave ----------------------------------------------------------------------


def test_key_is_shown_once_and_only_its_fingerprint_is_stored(tmp_path: Path) -> None:
    key_file = tmp_path / "config" / "api_key.sha256"
    assert not has_key(key_file)

    key = generate_key(key_file)

    assert has_key(key_file) and len(key) >= 40
    assert key not in key_file.read_text()
    assert KeyChecker(key_file).check(key) and not KeyChecker(key_file).check("otra")
    assert generate_key(key_file) != key and not KeyChecker(key_file).check(key)  # la anterior deja de servir


def test_repeated_failures_pause_the_api(tmp_path: Path) -> None:
    key_file, clock = tmp_path / "k", Clock()
    key = generate_key(key_file)
    checker = KeyChecker(key_file, clock=clock)

    for _ in range(MAX_FAILURES):
        assert not checker.check("adivinando")
    assert checker.locked()
    clock.now += LOCKOUT_SECONDS + 1
    assert not checker.locked() and checker.check(key)


# --- Servidor -------------------------------------------------------------------


def test_only_listens_on_this_pc(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="127.0.0.1"):
        ApiServer(port=0, checker=None, bridge=None, quick_commands={}, today=dict, host="0.0.0.0")  # type: ignore[arg-type]


def test_app_files_are_public_and_locked_down(api: Api) -> None:
    status, headers, body = api.request("GET", "/", key=None)
    assert status == 200 and b"<title>JARVIS</title>" in body
    assert "default-src 'self'" in headers["Content-Security-Policy"] and headers["X-Frame-Options"] == "DENY"

    status, headers, body = api.request("GET", "/icon-180.png", key=None)
    assert status == 200 and body.startswith(b"\x89PNG") and headers["Content-Type"] == "image/png"
    assert api.request("GET", "/manifest.webmanifest", key=None)[0] == 200
    assert api.request("GET", "/.env", key=None)[0] == 404
    assert api.json("GET", "/api/salud", key=None) == (200, {"ok": True})


def test_api_requires_the_key(api: Api) -> None:
    assert api.json("GET", "/api/hoy", key=None)[0] == 401
    status, body = api.json("GET", "/api/hoy", key="equivocada")
    assert status == 401 and "api-clave" in body["error"]
    assert api.json("GET", "/api/hoy") == (200, {"dia": "lunes 2 de noviembre", "reuniones": []})
    assert api.json("GET", "/api/gasto") == (200, {"texto": "💸 Hoy: nada"})


def test_too_many_wrong_keys_lock_everyone_out_for_a_minute(api: Api) -> None:
    for _ in range(MAX_FAILURES):
        api.request("GET", "/api/hoy", key="adivinando")

    assert api.json("GET", "/api/hoy")[0] == 429  # ni con la clave correcta
    api.clock.now += LOCKOUT_SECONDS + 1
    assert api.json("GET", "/api/hoy")[0] == 200


def test_optional_tailscale_account_check(tmp_path: Path) -> None:
    api = Api(tmp_path, [], tailscale_user="diego@gmail.com")
    try:
        assert api.json("GET", "/api/hoy")[0] == 403
        ok = api.json("GET", "/api/hoy", headers={"Tailscale-User-Login": "Diego@gmail.com"})
        assert ok[0] == 200
    finally:
        api.server.shutdown()


@pytest.mark.parametrize(
    ("body", "headers", "status"),
    [
        (b"hola", {"Content-Type": "text/plain"}, 400),  # solo JSON (y así otro sitio web no puede enviarlo)
        (b"{no es json", None, 400),
        ({"otro": 1}, None, 400),
        ({"texto": "x" * 4001}, None, 413),
        (b"x" * 20000, None, 400),
    ],
)
def test_invalid_chat_requests(api: Api, body: Any, headers: dict[str, str] | None, status: int) -> None:
    assert api.request("POST", "/api/chat", body, headers=headers)[0] == status


def test_other_methods_are_refused(api: Api) -> None:
    assert api.request("OPTIONS", "/api/chat", key=None)[0] == 405  # sin CORS
    assert api.request("DELETE", "/api/hoy")[0] == 405


# --- Chat -----------------------------------------------------------------------


def test_chat_round_trip_without_logging_content(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    api = Api(tmp_path, [text_response("Tienes 3 reuniones hoy.")])
    try:
        with caplog.at_level("INFO", logger="jarvis.chat"):
            status, reply = api.json("POST", "/api/chat", {"texto": "¿Qué tengo hoy, Diego?"})
    finally:
        api.server.shutdown()

    assert status == 200 and reply["terminado"] and reply["pregunta"] is None
    assert reply["mensajes"] == [{"tipo": "texto", "texto": "Tienes 3 reuniones hoy."}]
    assert reply["texto"] == "Tienes 3 reuniones hoy."  # para que Siri lo lea
    assert "App: POST /api/chat → 200" in caplog.text and "Diego" not in caplog.text


def test_quick_commands_work_from_the_app(api: Api) -> None:
    status, reply = api.json("POST", "/api/chat", {"texto": "/gasto"})

    assert status == 200 and reply["texto"] == "💸 Hoy: nada" and api.client.messages.calls == []


EVENT = ("t1", "crear_evento", {"titulo": "Dentista", "inicio": "2026-11-02 15:00"})


def test_confirmation_with_buttons(tmp_path: Path) -> None:
    api = Api(tmp_path, [tool_response(EVENT), text_response("Listo, quedó agendado.")])
    try:
        status, first = api.json("POST", "/api/chat", {"texto": "Agéndame dentista a las 3"})
        question = first["pregunta"]
        yes = next(b["dato"] for b in question["botones"] if b["texto"] == "✅ Sí")
        status, second = api.json("POST", "/api/boton", {"dato": yes})
    finally:
        api.server.shutdown()

    assert first["terminado"] is False and question["texto"].startswith("Voy a agendar en tu calendario:\n«Dentista»")
    assert question["texto"] in first["texto"]  # el texto completo incluye la pregunta, para Siri
    assert status == 200 and second["terminado"] and second["pregunta"] is None
    assert second["mensajes"][0]["tipo"] == "actualiza" and second["mensajes"][0]["texto"].endswith("✅ Confirmado")
    assert second["texto"] == "Listo, quedó agendado."


def test_siri_can_answer_with_words(tmp_path: Path) -> None:
    api = Api(tmp_path, [tool_response(EVENT), text_response("No agendé nada.")])
    try:
        api.json("POST", "/api/chat", {"texto": "Agéndame dentista a las 3"})
        _, unclear = api.json("POST", "/api/chat", {"texto": "quizás"})
        _, final = api.json("POST", "/api/chat", {"texto": "no"})
    finally:
        api.server.shutdown()

    assert "«sí» o «no»" in unclear["texto"] and unclear["pregunta"] is not None  # la pregunta sigue abierta
    assert final["texto"] == "No agendé nada." and final["pregunta"] is None


def test_a_second_request_waits_its_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(channel_module, "BUSY_TIMEOUT_SECONDS", 0.01)
    bridge = ChatBridge(ApiChannel(), submit=lambda _event: None, reply_timeout=0.01)
    bridge._lock.acquire()

    with pytest.raises(BusyError):
        bridge.send_text("hola")


def test_slow_answers_arrive_with_the_next_request() -> None:
    channel = ApiChannel()
    bridge = ChatBridge(channel, submit=lambda _event: None, reply_timeout=0.01)

    late = bridge.send_text("¿y el clima?")
    channel.send_text("app", "Va a llover.")
    channel.event_finished(None)  # type: ignore[arg-type]
    next_reply = bridge.send_text("gracias")

    assert late.finished is False
    assert next_reply.messages[0]["texto"] == "Va a llover."


# --- Configuración y estado -----------------------------------------------------


def test_settings_and_status(tmp_path: Path) -> None:
    assert load_api_settings({}).enabled is False
    settings = load_api_settings({"JARVIS_API": "si", "JARVIS_API_PUERTO": "9000", "JARVIS_API_USUARIO": "Diego@Gmail.com"})
    assert (settings.port, settings.tailscale_user) == (9000, "diego@gmail.com")
    with pytest.raises(ConfigError, match="JARVIS_API_PUERTO"):
        load_api_settings({"JARVIS_API_PUERTO": "80"})

    key_file = tmp_path / "k"
    assert describe_api(ApiSettings(enabled=False)) == "desactivada (JARVIS_API=si la activa)"
    assert "falta la clave" in describe_api(ApiSettings(enabled=True, key_file=key_file))
    generate_key(key_file)
    assert describe_api(ApiSettings(enabled=True, key_file=key_file)) == (
        "activa en 127.0.0.1:8765 (publícala con «tailscale serve --bg 8765»)"
    )


def test_status_line(isolated_config_dir: Path) -> None:
    from jarvis.status import status_report

    assert "App del iPhone: desactivada (JARVIS_API=si la activa)" in status_report({"ANTHROPIC_API_KEY": "k"}, None, {})
