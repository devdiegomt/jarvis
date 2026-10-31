import http.client
import threading
from typing import Any

import pytest

from connection_fakes import FakeResponse, fake_pool, ok
from jarvis.telegram import client as client_module
from jarvis.telegram.client import MAX_IDLE_SECONDS, TelegramClient, TelegramConnectionError

TOKEN = "123456:secreto-del-bot"
OWNER = "987654321"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_consecutive_calls_reuse_the_connection(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    connections = fake_pool(monkeypatch, [ok(), ok({"message_id": 1}), ok({"message_id": 2})])
    client = TelegramClient(TOKEN)

    with caplog.at_level("INFO", logger="jarvis.chat"):
        client.send_typing(OWNER)
        client.send_message(OWNER, "hola")
        client.send_message(OWNER, "¿algo más?")

    assert len(connections) == 1 and len(connections[0].requests) == 3
    assert [r[1] for r in connections[0].requests] == [f"/bot{TOKEN}/sendChatAction"] + [f"/bot{TOKEN}/sendMessage"] * 2
    assert "Telegram sendChatAction en" in caplog.text and "(conexión nueva)" in caplog.text
    assert caplog.text.count("(conexión reutilizada)") == 2
    assert TOKEN not in caplog.text and "hola" not in caplog.text  # ni el token ni el contenido


def test_long_polling_is_not_logged(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    fake_pool(monkeypatch, [ok([])])

    with caplog.at_level("INFO", logger="jarvis.chat"):
        TelegramClient(TOKEN).get_updates(None)

    assert "getUpdates" not in caplog.text


def test_each_thread_has_its_own_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    connections = fake_pool(monkeypatch, [ok(), ok(), ok()])
    client = TelegramClient(TOKEN)

    client.get_me()
    worker = threading.Thread(target=client.get_me)
    worker.start()
    worker.join()
    client.get_me()

    assert [len(c.requests) for c in connections] == [2, 1]  # el hilo principal reutilizó la suya


def test_idle_connections_are_renewed_before_use(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    connections = fake_pool(monkeypatch, [ok(), ok(), ok()], clock=clock)
    client = TelegramClient(TOKEN)

    client.get_me()
    clock.now += MAX_IDLE_SECONDS - 1
    client.get_me()  # todavía fresca
    clock.now += MAX_IDLE_SECONDS + 1
    client.get_me()

    assert [len(c.requests) for c in connections] == [2, 1]
    assert connections[0].closed


@pytest.mark.parametrize("error", [http.client.RemoteDisconnected("cerrada"), BrokenPipeError(), ConnectionResetError()])
def test_a_connection_closed_by_telegram_is_retried_once_with_a_new_one(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    connections = fake_pool(monkeypatch, [ok(), error, ok({"message_id": 9})])
    client = TelegramClient(TOKEN)
    client.get_me()

    assert client.send_message(OWNER, "hola") == {"message_id": 9}
    assert len(connections) == 2 and connections[0].closed


def test_a_new_connection_that_fails_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    connections = fake_pool(monkeypatch, [http.client.RemoteDisconnected("cerrada"), ok()])

    with pytest.raises(TelegramConnectionError):
        TelegramClient(TOKEN).send_message(OWNER, "hola")

    assert len(connections) == 1  # una sola petición: nada de duplicar el mensaje


def test_timeouts_are_never_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    connections = fake_pool(monkeypatch, [ok(), TimeoutError("timed out"), ok()])
    client = TelegramClient(TOKEN)
    client.get_me()

    with pytest.raises(TelegramConnectionError, match="tiempo de espera"):
        client.send_message(OWNER, "hola")  # Telegram pudo recibirlo: reintentar podría duplicarlo

    assert sum(len(c.requests) for c in connections) == 2
    assert connections[0].closed


def test_connections_closed_by_the_server_are_not_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    connections = fake_pool(monkeypatch, [ok(will_close=True), ok()])
    client = TelegramClient(TOKEN)

    client.get_me()
    client.get_me()

    assert len(connections) == 2


def test_truncated_downloads_drop_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    connections = fake_pool(monkeypatch, [FakeResponse(200, b"x" * 500), ok()])

    with pytest.raises(client_module.TelegramError, match="demasiado grande"):
        client_module.http_download(f"https://api.telegram.org/file/bot{TOKEN}/a.oga", 5, 100)
    TelegramClient(TOKEN).get_me()

    assert len(connections) == 2 and connections[0].closed  # quedaban datos sin leer


def test_downloads_share_the_connection_and_are_labeled_without_the_token(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    connections = fake_pool(monkeypatch, [ok({"file_path": "voice/file_7.oga", "file_size": 3}), FakeResponse(200, b"Ogg")])

    with caplog.at_level("INFO", logger="jarvis.chat"):
        audio = TelegramClient(TOKEN).download_file("voz")

    assert audio == b"Ogg" and len(connections) == 1
    assert connections[0].requests[1][:2] == ("GET", f"/file/bot{TOKEN}/voice/file_7.oga")
    assert "Telegram descarga en" in caplog.text and TOKEN not in caplog.text


def test_timeout_is_applied_to_reused_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    connections = fake_pool(monkeypatch, [ok([]), ok()])
    client = TelegramClient(TOKEN)

    client.get_updates(None)
    client.get_me()

    assert connections[0].timeout == client_module.REQUEST_MARGIN_SECONDS


def test_system_proxy_is_used_with_a_tunnel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module.urllib.request, "getproxies", lambda: {"https": "http://ana:cl%40ve@proxy.local:3128"})
    monkeypatch.setattr(client_module.urllib.request, "proxy_bypass", lambda _host: False)

    conn: Any = client_module.open_https_connection("api.telegram.org", 5)

    assert (conn.host, conn.port) == ("proxy.local", 3128)
    assert (conn._tunnel_host, conn._tunnel_port) == ("api.telegram.org", 443)
    assert conn._tunnel_headers["Proxy-Authorization"] == "Basic YW5hOmNsQHZl"  # ana:cl@ve
