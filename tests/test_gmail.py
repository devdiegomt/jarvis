import base64
import email
from email import policy
from typing import Any

import httplib2
import pytest
from googleapiclient.errors import HttpError

from jarvis.google_auth import GoogleAuthError, GoogleNotAuthorizedError
from jarvis.notify import ConsoleNotifier, NotificationError, NotificationNotAuthorizedError
from jarvis.notify.gmail import GmailNotifier, build_raw_message


def decode(raw: str) -> email.message.EmailMessage:
    return email.message_from_bytes(base64.urlsafe_b64decode(raw), policy=policy.default)  # type: ignore[return-value]


class FakeSend:
    def __init__(self, result: Any) -> None:
        self._result = result

    def execute(self) -> Any:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeGmail:
    """Doble mínimo de la Gmail API: service.users().messages().send(...).execute()."""

    def __init__(self, result: Any = None) -> None:
        self.result = result if result is not None else {"id": "msg-1"}
        self.sent: list[dict[str, Any]] = []

    def users(self) -> "FakeGmail":
        return self

    def messages(self) -> "FakeGmail":
        return self

    def send(self, **kwargs: Any) -> FakeSend:
        self.sent.append(kwargs)
        return FakeSend(self.result)


def http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b"{}")


def test_raw_message_is_plain_text_utf8() -> None:
    message = decode(build_raw_message("yo@example.com", "Tu día: miércoles", "Reunión con José"))

    assert message["To"] == "yo@example.com"
    assert message["Subject"] == "Tu día: miércoles"
    assert message.get_content_type() == "text/plain"
    assert message.get_content().strip() == "Reunión con José"


def test_gmail_notifier_sends_to_configured_recipient() -> None:
    service = FakeGmail()

    GmailNotifier(lambda: service, "yo@example.com").send("Asunto", "Cuerpo")

    assert len(service.sent) == 1
    call = service.sent[0]
    assert call["userId"] == "me"
    assert decode(call["body"]["raw"])["To"] == "yo@example.com"


@pytest.mark.parametrize(
    ("error", "error_type", "expected"),
    [
        (http_error(401), NotificationNotAuthorizedError, "google-login"),
        (http_error(403), NotificationNotAuthorizedError, "Gmail API"),
        (http_error(400), NotificationError, "JARVIS_RESUMEN_DESTINATARIO"),
        (http_error(503), NotificationError, "503"),
        (httplib2.HttpLib2Error("caído"), NotificationError, "No pude conectar"),
        (TimeoutError("timeout"), NotificationError, "No pude conectar"),
    ],
)
def test_gmail_errors_become_notification_errors(error: Exception, error_type: type, expected: str) -> None:
    notifier = GmailNotifier(lambda: FakeGmail(result=error), "yo@example.com")

    with pytest.raises(error_type, match=expected):
        notifier.send("Asunto", "Cuerpo")


@pytest.mark.parametrize(
    ("error", "error_type"),
    [(GoogleNotAuthorizedError("falta permiso"), NotificationNotAuthorizedError), (GoogleAuthError("sin red"), NotificationError)],
)
def test_auth_errors_become_notification_errors(error: Exception, error_type: type) -> None:
    def factory() -> FakeGmail:
        raise error

    with pytest.raises(error_type, match=str(error)):
        GmailNotifier(factory, "yo@example.com").send("Asunto", "Cuerpo")


def test_console_notifier_prints_instead_of_sending() -> None:
    written: list[str] = []

    ConsoleNotifier(write=written.append).send("Asunto", "Cuerpo")

    assert written == ["Asunto: Asunto\n\nCuerpo"]
