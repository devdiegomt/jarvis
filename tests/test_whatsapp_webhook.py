import hashlib
import hmac
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from jarvis.whatsapp.webhook import (
    IncomingMessage,
    WebhookConfig,
    build_server,
    extract_messages,
    is_valid_signature,
)

APP_SECRET = "secreto-de-la-app"
PHONE_NUMBER_ID = "12345"
OWNER = "573001234567"


def payload(*messages: dict[str, Any], phone_number_id: str = PHONE_NUMBER_ID) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": phone_number_id},
                            "messages": list(messages),
                        },
                    }
                ],
            }
        ],
    }


def text_message(message_id: str = "wamid.1", sender: str = OWNER, body: str = "hola") -> dict[str, Any]:
    return {"id": message_id, "from": sender, "type": "text", "text": {"body": body}}


def sign(body: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# --- Funciones puras --------------------------------------------------------


def test_valid_and_invalid_signatures() -> None:
    body = b'{"a": 1}'

    assert is_valid_signature(APP_SECRET, body, sign(body))
    assert not is_valid_signature(APP_SECRET, body, sign(body, secret="otro"))
    assert not is_valid_signature(APP_SECRET, body, None)
    assert not is_valid_signature(APP_SECRET, body, "md5=abc")


def test_extract_text_and_non_text_messages() -> None:
    image = {"id": "wamid.2", "from": OWNER, "type": "image", "image": {"id": "media"}}

    messages = extract_messages(payload(text_message(), image), PHONE_NUMBER_ID)

    assert messages == [
        IncomingMessage(id="wamid.1", sender=OWNER, text="hola"),
        IncomingMessage(id="wamid.2", sender=OWNER, text=None),
    ]


def test_extract_ignores_status_updates_and_other_numbers() -> None:
    statuses = payload()
    statuses["entry"][0]["changes"][0]["value"]["statuses"] = [{"id": "wamid.x", "status": "read"}]

    assert extract_messages(statuses, PHONE_NUMBER_ID) == []
    assert extract_messages(payload(text_message(), phone_number_id="otro"), PHONE_NUMBER_ID) == []


def test_extract_skips_malformed_messages() -> None:
    assert extract_messages(payload({"type": "text", "text": {"body": "sin id"}}), PHONE_NUMBER_ID) == []


# --- Servidor HTTP real en un puerto local ----------------------------------


class Received:
    def __init__(self) -> None:
        self.messages: list[IncomingMessage] = []
        self.seen: set[str] = set()

    def mark_processed(self, message_id: str) -> bool:
        if message_id in self.seen:
            return False
        self.seen.add(message_id)
        return True


@pytest.fixture
def server() -> Iterator[tuple[str, Received]]:
    received = Received()
    config = WebhookConfig(
        verify_token="token-verificacion",
        app_secret=APP_SECRET,
        phone_number_id=PHONE_NUMBER_ID,
        owner_number=OWNER,
        mark_processed=received.mark_processed,
        deliver=received.messages.append,
    )
    httpd = build_server("127.0.0.1", 0, config)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", received
    httpd.shutdown()
    httpd.server_close()


def get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, ""


def post(url: str, data: dict[str, Any], signature: str | None = "auto") -> int:
    body = json.dumps(data).encode()
    headers = {"Content-Type": "application/json"}
    if signature == "auto":
        signature = sign(body)
    if signature:
        headers["X-Hub-Signature-256"] = signature
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_meta_verification_handshake(server: tuple[str, Received]) -> None:
    base, _ = server

    ok = get(f"{base}/webhook?hub.mode=subscribe&hub.verify_token=token-verificacion&hub.challenge=123")
    wrong = get(f"{base}/webhook?hub.mode=subscribe&hub.verify_token=otro&hub.challenge=123")

    assert ok == (200, "123")
    assert wrong[0] == 403


def test_signed_message_from_owner_is_delivered(server: tuple[str, Received]) -> None:
    base, received = server

    assert post(f"{base}/webhook", payload(text_message())) == 200
    assert received.messages == [IncomingMessage("wamid.1", OWNER, "hola")]


def test_invalid_signature_is_rejected(server: tuple[str, Received]) -> None:
    base, received = server

    assert post(f"{base}/webhook", payload(text_message()), signature=sign(b"otro cuerpo")) == 401
    assert post(f"{base}/webhook", payload(text_message()), signature=None) == 401
    assert received.messages == []


def test_messages_from_other_numbers_are_ignored(server: tuple[str, Received]) -> None:
    base, received = server

    assert post(f"{base}/webhook", payload(text_message(sender="5215550000000"))) == 200
    assert received.messages == []


def test_duplicate_deliveries_are_ignored(server: tuple[str, Received]) -> None:
    base, received = server

    post(f"{base}/webhook", payload(text_message()))
    post(f"{base}/webhook", payload(text_message()))

    assert len(received.messages) == 1


def test_unknown_paths_return_404(server: tuple[str, Received]) -> None:
    base, _ = server

    assert get(f"{base}/otra")[0] == 404
    assert get(f"{base}/") == (200, "JARVIS está escuchando.")
