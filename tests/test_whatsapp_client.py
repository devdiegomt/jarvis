import io
import json
import urllib.error
from typing import Any

import pytest

from jarvis.whatsapp import client as client_module
from jarvis.whatsapp.client import WhatsAppClient, WhatsAppError, split_text


class FakePoster:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    def __call__(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((url, headers, payload))
        return {"messages": [{"id": "wamid.out"}]}


def make_client() -> tuple[WhatsAppClient, FakePoster]:
    poster = FakePoster()
    return WhatsAppClient("token-secreto", "12345", "v25.0", post=poster), poster


def test_send_text_builds_cloud_api_request() -> None:
    client, poster = make_client()

    client.send_text("573001234567", "Hola")

    url, headers, payload = poster.calls[0]
    assert url == "https://graph.facebook.com/v25.0/12345/messages"
    assert headers["Authorization"] == "Bearer token-secreto"
    assert payload == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "573001234567",
        "type": "text",
        "text": {"body": "Hola", "preview_url": False},
    }


def test_long_text_is_sent_in_several_messages() -> None:
    client, poster = make_client()

    client.send_text("573001234567", "a" * 5000)

    assert [len(call[2]["text"]["body"]) for call in poster.calls] == [4096, 904]


def test_mark_read_with_typing_indicator() -> None:
    client, poster = make_client()

    client.mark_read("wamid.1")

    assert poster.calls[0][2] == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.1",
        "typing_indicator": {"type": "text"},
    }


def test_split_text_prefers_paragraph_boundaries() -> None:
    text = "uno " * 10 + "\n\n" + "dos " * 10

    chunks = split_text(text, limit=50)

    assert chunks[0] == ("uno " * 10).strip()
    assert all(len(chunk) <= 50 for chunk in chunks)
    assert " ".join(chunks).split() == text.split()


def test_split_text_never_sends_empty_message() -> None:
    assert split_text("   ") == ["(sin respuesta)"]


def http_error(status: int, body: dict[str, Any]) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://graph.facebook.com", status, "error", {}, io.BytesIO(json.dumps(body).encode())  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (http_error(401, {"error": {"code": 190}}), "token de WhatsApp"),
        (http_error(400, {"error": {"code": 131030, "message": "Recipient not in allowed list"}}), "destinatarios permitidos"),
        (http_error(500, {"error": {"message": "Service unavailable"}}), "(500)"),
        (urllib.error.URLError("sin red"), "No pude conectar"),
    ],
)
def test_http_post_translates_errors(monkeypatch: pytest.MonkeyPatch, error: Exception, expected: str) -> None:
    def fake_urlopen(*_args: Any, **_kwargs: Any) -> Any:
        raise error

    monkeypatch.setattr(client_module.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(WhatsAppError, match=expected.replace("(", r"\(").replace(")", r"\)")):
        client_module.http_post("https://graph.facebook.com/x", {}, {})
