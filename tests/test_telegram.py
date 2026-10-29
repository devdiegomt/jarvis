import io
import json
import socket
import ssl
import urllib.error
from typing import Any

import pytest
import truststore

from jarvis.chat import ButtonAnswer, IncomingMessage
from jarvis.notify import NotificationError, NotificationNotAuthorizedError
from jarvis.notify.telegram import TelegramNotifier
from jarvis.telegram import client as client_module
from jarvis.telegram.bot import TelegramChannel, TelegramPoller, parse_update, wait_for_first_message
from jarvis.telegram.client import (
    TelegramAuthError,
    TelegramCertificateError,
    TelegramClient,
    TelegramConflictError,
    TelegramConnectionError,
    TelegramError,
)

TOKEN = "123456:secreto-del-bot"
OWNER = "987654321"


class FakeApi:
    """Sustituye las llamadas HTTP: registra cada método y devuelve respuestas guionizadas."""

    def __init__(self, results: dict[str, list[Any]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.results = results or {}

    def __call__(self, url: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        assert url.startswith(f"https://api.telegram.org/bot{TOKEN}/")
        method = url.rsplit("/", 1)[1]
        self.calls.append((method, params))
        queued = self.results.get(method)
        result = queued.pop(0) if queued else {"message_id": 1}
        if isinstance(result, Exception):
            raise result
        if isinstance(result, dict) and "ok" in result:
            return result
        return {"ok": True, "result": result}

    def methods(self) -> list[str]:
        return [method for method, _ in self.calls]


def private_message(update_id: int, user_id: str = OWNER, text: str | None = "hola") -> dict[str, Any]:
    message: dict[str, Any] = {
        "message_id": 10 + update_id,
        "from": {"id": int(user_id), "first_name": "Ana"},
        "chat": {"id": int(user_id), "type": "private"},
    }
    if text is not None:
        message["text"] = text
    return {"update_id": update_id, "message": message}


def button_click(update_id: int, data: str, user_id: str = OWNER) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb{update_id}",
            "from": {"id": int(user_id)},
            "message": {"message_id": 5, "chat": {"id": int(user_id), "type": "private"}},
            "data": data,
        },
    }


# --- Cliente ----------------------------------------------------------------


def test_send_message_with_buttons() -> None:
    api = FakeApi()

    TelegramClient(TOKEN, call=api).send_message(OWNER, "¿Confirmas?", buttons=[("✅ Sí", "x:si"), ("❌ No", "x:no")])

    method, params = api.calls[0]
    assert method == "sendMessage"
    assert params == {
        "chat_id": OWNER,
        "text": "¿Confirmas?",
        "reply_markup": {
            "inline_keyboard": [[{"text": "✅ Sí", "callback_data": "x:si"}, {"text": "❌ No", "callback_data": "x:no"}]]
        },
    }


def test_get_updates_uses_long_polling_and_offset() -> None:
    api = FakeApi({"getUpdates": [[]]})

    TelegramClient(TOKEN, call=api).get_updates(offset=42)

    assert api.calls[0][1] == {"timeout": 30, "allowed_updates": ["message", "callback_query"], "offset": 42}


@pytest.mark.parametrize(
    ("code", "error_type"),
    [(401, TelegramAuthError), (409, TelegramConflictError), (429, TelegramConnectionError), (400, TelegramError)],
)
def test_api_errors(code: int, error_type: type) -> None:
    api = FakeApi({"sendMessage": [{"ok": False, "error_code": code, "description": "x"}]})

    with pytest.raises(error_type):
        TelegramClient(TOKEN, call=api).send_message(OWNER, "hola")


def test_http_errors_never_expose_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"ok": False, "error_code": 401, "description": "Unauthorized"}).encode()

    def unauthorized(*_args: Any, **_kwargs: Any) -> Any:
        raise urllib.error.HTTPError(f"https://api.telegram.org/bot{TOKEN}/getMe", 401, "x", {}, io.BytesIO(body))  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.urllib.request, "urlopen", unauthorized)

    with pytest.raises(TelegramAuthError) as excinfo:
        TelegramClient(TOKEN).get_me()
    assert TOKEN not in str(excinfo.value)


def test_network_errors_are_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    def offline(*_args: Any, **_kwargs: Any) -> Any:
        raise urllib.error.URLError("sin red")

    monkeypatch.setattr(client_module.urllib.request, "urlopen", offline)

    with pytest.raises(TelegramConnectionError) as excinfo:
        TelegramClient(TOKEN).get_me()
    assert excinfo.value.__cause__ is None  # sin la excepción original, que incluye la URL


@pytest.mark.parametrize(
    ("reason", "error_type", "expected"),
    [
        (
            ssl.SSLCertVerificationError("self-signed certificate in certificate chain"),
            TelegramCertificateError,
            "antivirus o proxy",
        ),
        (socket.gaierror("getaddrinfo failed"), TelegramConnectionError, "no se encontró api.telegram.org"),
        (TimeoutError("timed out"), TelegramConnectionError, "tiempo de espera"),
    ],
)
def test_network_errors_explain_the_cause(
    monkeypatch: pytest.MonkeyPatch, reason: Exception, error_type: type, expected: str
) -> None:
    def failing(*_args: Any, **_kwargs: Any) -> Any:
        raise urllib.error.URLError(reason)

    monkeypatch.setattr(client_module.urllib.request, "urlopen", failing)

    with pytest.raises(error_type, match=expected) as excinfo:
        TelegramClient(TOKEN).get_me()
    assert TOKEN not in str(excinfo.value)


def test_certificate_errors_are_not_retried() -> None:
    assert not issubclass(TelegramCertificateError, TelegramConnectionError)


def test_https_uses_the_operating_system_trust_store(monkeypatch: pytest.MonkeyPatch) -> None:
    contexts: list[Any] = []

    def capture(_request: Any, timeout: float, context: Any) -> Any:
        contexts.append(context)
        return io.BytesIO(b'{"ok": true, "result": {}}')

    monkeypatch.setattr(client_module.urllib.request, "urlopen", capture)

    TelegramClient(TOKEN).get_me()

    assert isinstance(contexts[0], truststore.SSLContext)
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED


# --- Recepción de actualizaciones -------------------------------------------


def test_owner_messages_and_buttons_are_parsed() -> None:
    assert parse_update(private_message(1), OWNER) == IncomingMessage(f"{OWNER}:11", OWNER, "hola")
    assert parse_update(private_message(2, text=None), OWNER) == IncomingMessage(f"{OWNER}:12", OWNER, None)
    assert parse_update(button_click(3, "abc:si"), OWNER) == ButtonAnswer("cb3", OWNER, "abc:si")


def test_other_users_and_groups_are_ignored() -> None:
    group = private_message(1)
    group["message"]["chat"] = {"id": -100, "type": "group"}

    assert parse_update(private_message(1, user_id="111"), OWNER) is None
    assert parse_update(button_click(2, "abc:si", user_id="111"), OWNER) is None
    assert parse_update(group, OWNER) is None
    assert parse_update({"update_id": 3, "edited_message": {}}, OWNER) is None


def test_poller_delivers_events_and_advances_offset() -> None:
    api = FakeApi({"getUpdates": [[private_message(7), private_message(8, user_id="111")], []]})
    delivered: list[Any] = []
    seen: set[str] = set()

    def mark(key: str) -> bool:
        if key in seen:
            return False
        seen.add(key)
        return True

    poller = TelegramPoller(TelegramClient(TOKEN, call=api), OWNER, delivered.append, mark)

    assert poller.poll_once() == 1
    poller.poll_once()

    assert [event.text for event in delivered] == ["hola"]
    assert api.calls[1][1]["offset"] == 9  # confirma también la actualización ignorada


def test_poller_skips_updates_already_processed() -> None:
    api = FakeApi({"getUpdates": [[private_message(7)]]})
    delivered: list[Any] = []

    poller = TelegramPoller(TelegramClient(TOKEN, call=api), OWNER, delivered.append, lambda _key: False)

    assert poller.poll_once() == 0
    assert delivered == []


def test_poller_retries_network_errors_with_backoff() -> None:
    offline = TelegramConnectionError("sin red")
    fatal = TelegramAuthError("token inválido")
    api = FakeApi({"getUpdates": [offline, offline, [], offline, fatal]})
    waits: list[float] = []

    poller = TelegramPoller(TelegramClient(TOKEN, call=api), OWNER, lambda _e: None, lambda _k: True, sleep=waits.append)

    with pytest.raises(TelegramAuthError):
        poller.run_forever()
    assert waits == [1.0, 2.0, 1.0]  # tras una consulta correcta, la espera vuelve a empezar


# --- Canal ------------------------------------------------------------------


def test_channel_confirmation_round_trip() -> None:
    api = FakeApi({"sendMessage": [{"message_id": 77}]})
    channel = TelegramChannel(TelegramClient(TOKEN, call=api))

    handle = channel.ask_confirmation(OWNER, "¿Envío?", [("✅ Sí", "x:si"), ("❌ No", "x:no")])
    channel.close_confirmation(OWNER, handle, "¿Envío?\n\n✅ Confirmado")
    channel.acknowledge(ButtonAnswer("cb1", OWNER, "x:si"), "")

    assert handle == 77
    assert api.calls[1] == ("editMessageText", {"chat_id": OWNER, "message_id": 77, "text": "¿Envío?\n\n✅ Confirmado"})
    assert api.calls[2] == ("answerCallbackQuery", {"callback_query_id": "cb1", "text": ""})


def test_channel_splits_long_messages() -> None:
    api = FakeApi()

    TelegramChannel(TelegramClient(TOKEN, call=api)).send_text(OWNER, "a" * 5000)

    assert [len(params["text"]) for _, params in api.calls] == [4096, 904]


# --- Resumen por Telegram ---------------------------------------------------


def test_notifier_sends_subject_and_body() -> None:
    api = FakeApi()

    TelegramNotifier(TelegramClient(TOKEN, call=api), OWNER).send("Tu día: jueves", "Agenda…")

    assert api.calls == [("sendMessage", {"chat_id": OWNER, "text": "Tu día: jueves\n\nAgenda…"})]


@pytest.mark.parametrize(
    ("error", "error_type"),
    [(TelegramAuthError("token"), NotificationNotAuthorizedError), (TelegramConnectionError("red"), NotificationError)],
)
def test_notifier_errors(error: Exception, error_type: type) -> None:
    api = FakeApi({"sendMessage": [error]})

    with pytest.raises(error_type):
        TelegramNotifier(TelegramClient(TOKEN, call=api), OWNER).send("a", "b")


# --- Vinculación ------------------------------------------------------------


def test_wait_for_first_message_returns_sender_and_confirms_it() -> None:
    api = FakeApi({"getUpdates": [TelegramConnectionError("red"), [], [private_message(5)], []]})

    user = wait_for_first_message(TelegramClient(TOKEN, call=api), 60, clock=lambda: 0.0, sleep=lambda _s: None)

    assert user == {"id": int(OWNER), "first_name": "Ana"}
    assert api.calls[-2] == ("getUpdates", {"timeout": 0, "allowed_updates": ["message", "callback_query"], "offset": 6})
    assert api.methods()[-1] == "sendMessage"


def test_wait_for_first_message_times_out() -> None:
    ticks = iter([0.0, 10.0, 999.0])
    api = FakeApi({"getUpdates": [[]]})

    assert wait_for_first_message(TelegramClient(TOKEN, call=api), 60, clock=lambda: next(ticks)) is None


def test_background_poller_waits_when_another_copy_uses_the_bot() -> None:
    conflict = TelegramConflictError("otra copia")
    fatal = TelegramAuthError("token inválido")
    api = FakeApi({"getUpdates": [conflict, conflict, fatal]})
    waits: list[float] = []

    poller = TelegramPoller(TelegramClient(TOKEN, call=api), OWNER, lambda _e: None, lambda _k: True, sleep=waits.append)

    with pytest.raises(TelegramAuthError):
        poller.run_forever(wait_on_conflict=True)
    assert waits == [60, 60]


def test_manual_poller_stops_when_another_copy_uses_the_bot() -> None:
    api = FakeApi({"getUpdates": [TelegramConflictError("otra copia")]})

    poller = TelegramPoller(TelegramClient(TOKEN, call=api), OWNER, lambda _e: None, lambda _k: True)

    with pytest.raises(TelegramConflictError):
        poller.run_forever()
