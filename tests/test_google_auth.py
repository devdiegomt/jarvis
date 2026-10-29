import json
import stat
from pathlib import Path
from typing import Any

import pytest
from google.auth.exceptions import RefreshError, TransportError

from jarvis import google_auth
from jarvis.google_auth import (
    CALENDAR_SCOPE,
    GMAIL_SEND_SCOPE,
    GoogleAuthError,
    GoogleNotAuthorizedError,
)

BOTH_SCOPES = [CALENDAR_SCOPE, GMAIL_SEND_SCOPE]


class FakeCredentials:
    def __init__(
        self,
        valid: bool = True,
        refresh_token: str | None = "r",
        refresh_error: Exception | None = None,
        scopes: list[str] | None = None,
        granted_scopes: list[str] | None = None,
    ) -> None:
        self.valid = valid
        self.refresh_token = refresh_token
        self.refresh_error = refresh_error
        self.scopes = scopes if scopes is not None else [CALENDAR_SCOPE]
        self.granted_scopes = granted_scopes
        self.refreshed = False

    def refresh(self, _request: Any) -> None:
        if self.refresh_error:
            raise self.refresh_error
        self.refreshed = True
        self.valid = True

    def to_json(self) -> str:
        return json.dumps({"token": "nuevo", "scopes": self.scopes})


@pytest.fixture
def token_file(tmp_path: Path) -> Path:
    path = tmp_path / "token.json"
    path.write_text("{}")
    return path


def use_credentials(monkeypatch: pytest.MonkeyPatch, credentials: Any) -> None:
    monkeypatch.setattr(
        google_auth.Credentials, "from_authorized_user_file", lambda *_args, **_kwargs: credentials
    )


def use_flow(monkeypatch: pytest.MonkeyPatch, credentials: FakeCredentials) -> list[list[str]]:
    requested: list[list[str]] = []

    class FakeFlow:
        def run_local_server(self, **_kwargs: Any) -> FakeCredentials:
            return credentials

    def from_client_secrets_file(_path: str, scopes: list[str]) -> FakeFlow:
        requested.append(scopes)
        return FakeFlow()

    monkeypatch.setattr(google_auth.InstalledAppFlow, "from_client_secrets_file", from_client_secrets_file)
    return requested


# --- load_credentials -------------------------------------------------------


def test_missing_token_is_not_authorized(tmp_path: Path) -> None:
    with pytest.raises(GoogleNotAuthorizedError, match="google-login"):
        google_auth.load_credentials(tmp_path / "no-existe.json", [CALENDAR_SCOPE])


def test_invalid_token_file_is_not_authorized(token_file: Path) -> None:
    token_file.write_text("esto no es json")

    with pytest.raises(GoogleNotAuthorizedError):
        google_auth.load_credentials(token_file, [CALENDAR_SCOPE])


def test_valid_token_is_returned_as_is(monkeypatch: pytest.MonkeyPatch, token_file: Path) -> None:
    credentials = FakeCredentials(valid=True)
    use_credentials(monkeypatch, credentials)

    assert google_auth.load_credentials(token_file, [CALENDAR_SCOPE]) is credentials
    assert not credentials.refreshed


def test_token_without_required_scope_asks_to_login_again(
    monkeypatch: pytest.MonkeyPatch, token_file: Path
) -> None:
    # Token de la v0.2: solo calendario.
    use_credentials(monkeypatch, FakeCredentials(scopes=[CALENDAR_SCOPE]))

    with pytest.raises(GoogleNotAuthorizedError, match="enviar correos"):
        google_auth.load_credentials(token_file, [GMAIL_SEND_SCOPE])


def test_calendar_only_token_still_works_for_calendar(
    monkeypatch: pytest.MonkeyPatch, token_file: Path
) -> None:
    credentials = FakeCredentials(scopes=[CALENDAR_SCOPE])
    use_credentials(monkeypatch, credentials)

    assert google_auth.load_credentials(token_file, [CALENDAR_SCOPE]) is credentials


def test_expired_token_is_refreshed_and_saved(monkeypatch: pytest.MonkeyPatch, token_file: Path) -> None:
    credentials = FakeCredentials(valid=False)
    use_credentials(monkeypatch, credentials)

    google_auth.load_credentials(token_file, [CALENDAR_SCOPE])

    assert credentials.refreshed
    assert json.loads(token_file.read_text())["token"] == "nuevo"


def test_expired_token_without_refresh_token_is_not_authorized(
    monkeypatch: pytest.MonkeyPatch, token_file: Path
) -> None:
    use_credentials(monkeypatch, FakeCredentials(valid=False, refresh_token=None))

    with pytest.raises(GoogleNotAuthorizedError):
        google_auth.load_credentials(token_file, [CALENDAR_SCOPE])


@pytest.mark.parametrize(
    ("error", "error_type"),
    [(RefreshError("revocado"), GoogleNotAuthorizedError), (TransportError("sin red"), GoogleAuthError)],
)
def test_refresh_failures(
    monkeypatch: pytest.MonkeyPatch, token_file: Path, error: Exception, error_type: type
) -> None:
    use_credentials(monkeypatch, FakeCredentials(valid=False, refresh_error=error))

    with pytest.raises(error_type):
        google_auth.load_credentials(token_file, [CALENDAR_SCOPE])


# --- save_credentials -------------------------------------------------------


def test_saved_token_is_private(tmp_path: Path) -> None:
    token_file = tmp_path / "subdir" / "token.json"

    google_auth.save_credentials(FakeCredentials(), token_file)  # type: ignore[arg-type]

    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


def test_save_credentials_can_override_scopes(tmp_path: Path) -> None:
    token_file = tmp_path / "token.json"

    google_auth.save_credentials(FakeCredentials(scopes=BOTH_SCOPES), token_file, scopes=[CALENDAR_SCOPE])  # type: ignore[arg-type]

    assert json.loads(token_file.read_text())["scopes"] == [CALENDAR_SCOPE]


# --- login ------------------------------------------------------------------


def test_login_without_credentials_file_explains_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(GoogleAuthError, match="Google Cloud Console"):
        google_auth.login(tmp_path / "credentials.json", tmp_path / "token.json", [CALENDAR_SCOPE])


def test_login_with_invalid_credentials_file(tmp_path: Path) -> None:
    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text(json.dumps({"otro": {}}))

    with pytest.raises(GoogleAuthError, match="App de escritorio"):
        google_auth.login(credentials_file, tmp_path / "token.json", [CALENDAR_SCOPE])


def test_login_requests_scopes_and_saves_granted_ones(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    requested = use_flow(monkeypatch, FakeCredentials(scopes=BOTH_SCOPES, granted_scopes=BOTH_SCOPES))
    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text("{}")
    token_file = tmp_path / "token.json"

    google_auth.login(credentials_file, token_file, BOTH_SCOPES)

    assert requested == [BOTH_SCOPES]
    assert json.loads(token_file.read_text())["scopes"] == BOTH_SCOPES


def test_login_fails_if_user_unchecks_a_permission(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    use_flow(monkeypatch, FakeCredentials(scopes=BOTH_SCOPES, granted_scopes=[CALENDAR_SCOPE]))
    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text("{}")
    token_file = tmp_path / "token.json"

    with pytest.raises(GoogleAuthError, match="enviar correos"):
        google_auth.login(credentials_file, token_file, BOTH_SCOPES)
    assert not token_file.exists()
