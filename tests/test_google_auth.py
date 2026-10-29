import json
import stat
from pathlib import Path
from typing import Any

import pytest
from google.auth.exceptions import RefreshError, TransportError

from jarvis.agenda import CalendarError, CalendarNotAuthorizedError
from jarvis.agenda import google_auth


class FakeCredentials:
    def __init__(self, valid: bool = True, refresh_token: str | None = "r", refresh_error: Exception | None = None) -> None:
        self.valid = valid
        self.refresh_token = refresh_token
        self.refresh_error = refresh_error
        self.refreshed = False

    def refresh(self, _request: Any) -> None:
        if self.refresh_error:
            raise self.refresh_error
        self.refreshed = True
        self.valid = True

    def to_json(self) -> str:
        return json.dumps({"token": "nuevo"})


@pytest.fixture
def token_file(tmp_path: Path) -> Path:
    path = tmp_path / "token.json"
    path.write_text("{}")
    return path


def use_credentials(monkeypatch: pytest.MonkeyPatch, credentials: Any) -> None:
    monkeypatch.setattr(
        google_auth.Credentials, "from_authorized_user_file", lambda *_args, **_kwargs: credentials
    )


def test_missing_token_is_not_authorized(tmp_path: Path) -> None:
    with pytest.raises(CalendarNotAuthorizedError, match="google-login"):
        google_auth.load_credentials(tmp_path / "no-existe.json")


def test_invalid_token_file_is_not_authorized(token_file: Path) -> None:
    token_file.write_text("esto no es json")

    with pytest.raises(CalendarNotAuthorizedError):
        google_auth.load_credentials(token_file)


def test_valid_token_is_returned_as_is(monkeypatch: pytest.MonkeyPatch, token_file: Path) -> None:
    credentials = FakeCredentials(valid=True)
    use_credentials(monkeypatch, credentials)

    assert google_auth.load_credentials(token_file) is credentials
    assert not credentials.refreshed


def test_expired_token_is_refreshed_and_saved(monkeypatch: pytest.MonkeyPatch, token_file: Path) -> None:
    credentials = FakeCredentials(valid=False)
    use_credentials(monkeypatch, credentials)

    google_auth.load_credentials(token_file)

    assert credentials.refreshed
    assert json.loads(token_file.read_text()) == {"token": "nuevo"}


def test_expired_token_without_refresh_token_is_not_authorized(
    monkeypatch: pytest.MonkeyPatch, token_file: Path
) -> None:
    use_credentials(monkeypatch, FakeCredentials(valid=False, refresh_token=None))

    with pytest.raises(CalendarNotAuthorizedError):
        google_auth.load_credentials(token_file)


@pytest.mark.parametrize(
    ("error", "error_type"),
    [(RefreshError("revocado"), CalendarNotAuthorizedError), (TransportError("sin red"), CalendarError)],
)
def test_refresh_failures(monkeypatch: pytest.MonkeyPatch, token_file: Path, error: Exception, error_type: type) -> None:
    use_credentials(monkeypatch, FakeCredentials(valid=False, refresh_error=error))

    with pytest.raises(error_type):
        google_auth.load_credentials(token_file)


def test_saved_token_is_private(tmp_path: Path) -> None:
    token_file = tmp_path / "subdir" / "token.json"

    google_auth.save_credentials(FakeCredentials(), token_file)  # type: ignore[arg-type]

    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


def test_login_without_credentials_file_explains_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(CalendarError, match="Google Cloud Console"):
        google_auth.login(tmp_path / "credentials.json", tmp_path / "token.json")


def test_login_with_invalid_credentials_file(tmp_path: Path) -> None:
    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text(json.dumps({"otro": {}}))

    with pytest.raises(CalendarError, match="App de escritorio"):
        google_auth.login(credentials_file, tmp_path / "token.json")


def test_login_saves_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    requested_scopes: list[list[str]] = []

    class FakeFlow:
        def run_local_server(self, **_kwargs: Any) -> FakeCredentials:
            return FakeCredentials()

    def from_client_secrets_file(_path: str, scopes: list[str]) -> FakeFlow:
        requested_scopes.append(scopes)
        return FakeFlow()

    monkeypatch.setattr(google_auth.InstalledAppFlow, "from_client_secrets_file", from_client_secrets_file)
    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text("{}")
    token_file = tmp_path / "token.json"

    google_auth.login(credentials_file, token_file)

    assert requested_scopes == [["https://www.googleapis.com/auth/calendar.readonly"]]
    assert json.loads(token_file.read_text()) == {"token": "nuevo"}
