import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httplib2
import pytest
from googleapiclient.errors import HttpError

from jarvis.agenda import SampleCalendar
from jarvis.config import ConfigError, MailSettings, ProactiveSettings, load_mail_settings
from jarvis.gmail_reader import Email, GmailReader, MailNotAuthorizedError, watched_query
from jarvis.mail_watch import WatchList, normalize_pattern
from jarvis.proactive import NoticeLog, ProactiveNotifier, mail_alert
from jarvis.tasks import TaskStore
from jarvis.tools import build_registry

TZ = ZoneInfo("America/Bogota")
OWNER = "987654321"

# --- Configuración y lista de vigilados -------------------------------------


def test_mail_settings() -> None:
    assert load_mail_settings({}) == MailSettings(True, 2)
    assert load_mail_settings({"JARVIS_CORREO": "no", "JARVIS_CORREO_MINUTOS": "5"}) == MailSettings(False, 5)
    with pytest.raises(ConfigError, match="JARVIS_CORREO_MINUTOS"):
        load_mail_settings({"JARVIS_CORREO_MINUTOS": "0"})


@pytest.mark.parametrize(
    ("value", "pattern"),
    [("Laura@Acme.com", "laura@acme.com"), ("acme.com", "@acme.com"), (" @ACME.com.co ", "@acme.com.co")],
)
def test_patterns_are_normalized(value: str, pattern: str) -> None:
    assert normalize_pattern(value) == pattern


@pytest.mark.parametrize("value", ["laura", "laura@", "@acme", "acme com"])
def test_invalid_patterns(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_pattern(value)


def test_watch_list(tmp_path: Path) -> None:
    watched = WatchList(tmp_path / "jarvis.db")

    assert watched.add("laura@acme.com") == ("laura@acme.com", True)
    assert watched.add("Laura@acme.com")[1] is False
    watched.add("globex.com")

    assert watched.all() == ["@globex.com", "laura@acme.com"]
    assert watched.matches("LAURA@acme.com") and watched.matches("ceo@globex.com")
    assert not watched.matches("pedro@acme.com") and not watched.matches("x@notglobex.com")
    assert watched.remove("acme.com") is None and watched.remove("laura@acme.com") == "laura@acme.com"


def test_watched_query() -> None:
    query = watched_query(["@acme.com", "laura@globex.com"], after=datetime(2026, 11, 2, 12, 0, tzinfo=UTC))

    assert query == "from:(acme.com OR laura@globex.com) -in:sent -in:chats after:1793620800"


# --- Lector de Gmail --------------------------------------------------------


class Request:
    def __init__(self, result: Any) -> None:
        self.result = result

    def execute(self) -> Any:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Messages:
    def __init__(self, listing: Any, messages: dict[str, Any]) -> None:
        self.listing = listing
        self.messages = messages
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list(self, **kwargs: Any) -> Request:
        self.calls.append(("list", kwargs))
        return Request(self.listing)

    def get(self, **kwargs: Any) -> Request:
        self.calls.append(("get", kwargs))
        return Request(self.messages[kwargs["id"]])


def gmail(listing: Any, messages: dict[str, Any] | None = None) -> tuple[GmailReader, Messages]:
    resource = Messages(listing, messages or {})
    users = type("U", (), {"messages": lambda _self: resource})()
    service = type("S", (), {"users": lambda _self: users})()
    return GmailReader(lambda: service, TZ), resource


def message(msg_id: str, sender: str, subject: str, received: datetime, body: str = "", snippet: str = "") -> dict:
    data = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    return {
        "id": msg_id,
        "internalDate": str(int(received.timestamp() * 1000)),
        "snippet": snippet,
        "payload": {
            "headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}],
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/html", "body": {"data": "PGI+aHRtbDwvYj4"}},
                {"mimeType": "text/plain", "body": {"data": data}},
            ],
        },
    }


NOON = datetime(2026, 11, 2, 12, 0, tzinfo=TZ)


def test_search_reads_only_metadata() -> None:
    reader, resource = gmail(
        {"messages": [{"id": "m1"}]},
        {"m1": message("m1", "Laura Gómez <Laura@Acme.com>", "Propuesta", NOON, snippet="Hola &amp; saludos")},
    )

    [email] = reader.search("from:acme.com")

    assert email == Email("m1", "Laura Gómez", "laura@acme.com", "Propuesta", "Hola & saludos", NOON)
    assert resource.calls[1][1]["format"] == "metadata"
    assert ("list", {"userId": "me", "q": "from:acme.com", "maxResults": 10}) == resource.calls[0]


def test_read_prefers_plain_text_and_trims() -> None:
    reader, _ = gmail({}, {"m1": message("m1", "laura@acme.com", "Propuesta", NOON, body="Hola Diego, " * 1000)})

    email, body = reader.read("m1")

    assert email.sender_name == "laura@acme.com"
    assert body.startswith("Hola Diego,") and body.endswith("[…recortado]") and len(body) < 6100


def test_missing_permission_is_explained() -> None:
    reader, _ = gmail(HttpError(httplib2.Response({"status": 403}), b"{}"))

    with pytest.raises(MailNotAuthorizedError, match="google-login"):
        reader.search("x")


# --- Avisos -----------------------------------------------------------------


class Reader:
    def __init__(self, emails: list[Email], error: Exception | None = None) -> None:
        self.emails = emails
        self.error = error
        self.queries: list[str] = []

    def search(self, query: str, max_results: int = 10) -> list[Email]:
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.emails


class Channel:
    name = "prueba"

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_text(self, to: str, text: str) -> None:
        self.sent.append(text)


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


def email(msg_id: str, sender: str, received: datetime, subject: str = "Propuesta") -> Email:
    return Email(msg_id, "Laura Gómez", sender, subject, "Te adjunto los cambios.", received)


def mail_notifier(tmp_path: Path, clock: Clock, reader: Reader, channel: Channel) -> ProactiveNotifier:
    db = tmp_path / "jarvis.db"
    return ProactiveNotifier(
        calendar=SampleCalendar(TZ),
        tasks=TaskStore(db, now=clock),
        channel=channel,
        owner=OWNER,
        settings=ProactiveSettings(0, None),
        log=NoticeLog(db),
        timezone=TZ,
        now=clock,
        mail=reader,  # type: ignore[arg-type]
        watched=WatchList(db),
        mail_interval=timedelta(minutes=2),
    )


def watch(tmp_path: Path, pattern: str, since: datetime) -> None:
    WatchList(tmp_path / "jarvis.db").add(pattern)
    import sqlite3

    with sqlite3.connect(tmp_path / "jarvis.db") as conn:
        conn.execute("UPDATE watched_senders SET created_at = ?", (since.astimezone(UTC).isoformat(),))


def test_new_client_mail_is_announced_once(tmp_path: Path) -> None:
    clock, channel = Clock(NOON), Channel()
    watch(tmp_path, "acme.com", NOON - timedelta(days=10))
    reader = Reader([])
    proactive = mail_notifier(tmp_path, clock, reader, channel)

    proactive.check()  # primera revisión: marca el inicio, sin correos
    reader.emails = [email("m1", "laura@acme.com", NOON + timedelta(minutes=1))]
    clock.moment = NOON + timedelta(minutes=2)
    proactive.check()
    clock.moment = NOON + timedelta(minutes=4)
    proactive.check()  # el mismo correo no se repite

    assert channel.sent == ["📧 Correo de Laura Gómez (laura@acme.com)\n«Propuesta»\nTe adjunto los cambios."]
    assert reader.queries[0].startswith("from:(acme.com)")


def test_old_mail_is_never_announced(tmp_path: Path) -> None:
    clock, channel = Clock(NOON), Channel()
    watch(tmp_path, "acme.com", NOON - timedelta(days=10))
    reader = Reader([email("viejo", "laura@acme.com", NOON - timedelta(hours=1))])

    mail_notifier(tmp_path, clock, reader, channel).check()  # al activar: lo anterior no se avisa

    assert channel.sent == []


def test_mail_from_before_a_contact_was_added_is_not_announced(tmp_path: Path) -> None:
    clock, channel = Clock(NOON), Channel()
    reader = Reader([])
    proactive = mail_notifier(tmp_path, clock, reader, channel)
    proactive.check()  # los avisos ya estaban activos

    clock.moment = NOON + timedelta(hours=3)
    watch(tmp_path, "globex.com", NOON + timedelta(hours=3))  # se agrega ahora
    reader.emails = [email("antes", "ceo@globex.com", NOON + timedelta(hours=1))]
    proactive.check()

    assert channel.sent == []


def test_unwatched_senders_are_ignored(tmp_path: Path) -> None:
    clock, channel = Clock(NOON), Channel()
    watch(tmp_path, "acme.com", NOON - timedelta(days=1))
    reader = Reader([])
    proactive = mail_notifier(tmp_path, clock, reader, channel)
    proactive.check()

    reader.emails = [email("m1", "x@notacme.com", NOON + timedelta(minutes=1))]
    clock.moment = NOON + timedelta(minutes=3)
    proactive.check()

    assert channel.sent == []


def test_no_watched_contacts_means_no_gmail_calls(tmp_path: Path) -> None:
    reader = Reader([])
    mail_notifier(tmp_path, Clock(NOON), reader, Channel()).check()

    assert reader.queries == []


def test_gmail_is_checked_every_interval_and_permission_problems_pause_quietly(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    clock = Clock(NOON)
    watch(tmp_path, "acme.com", NOON - timedelta(days=1))
    reader = Reader([], error=MailNotAuthorizedError("Falta el permiso"))
    proactive = mail_notifier(tmp_path, clock, reader, Channel())

    with caplog.at_level("WARNING", logger="jarvis.chat"):
        for minute in range(5):
            clock.moment = NOON + timedelta(minutes=minute)
            proactive.check()

    assert len(reader.queries) == 3  # minutos 0, 2 y 4
    assert caplog.text.count("Avisos de correo en pausa") == 1


def test_mail_alert_text() -> None:
    plain = Email("m", "laura@acme.com", "laura@acme.com", "Hola", "x" * 300, NOON)

    text = mail_alert(plain)

    assert text.startswith("📧 Correo de laura@acme.com\n«Hola»\n") and text.endswith("…")


# --- Tools, /clientes y estado ----------------------------------------------


def test_mail_tools(tmp_path: Path) -> None:
    db = tmp_path / "jarvis.db"
    reader, resource = gmail(
        {"messages": [{"id": "m1"}]},
        {"m1": message("m1", "Laura <laura@acme.com>", "Propuesta", NOON, body="Paga ya la factura.", snippet="Paga")},
    )
    registry = build_registry(SampleCalendar(TZ), watched=WatchList(db), mail=reader)

    added = json.loads(registry.execute("vigilar_contacto", {"correo_o_dominio": "acme.com"}).content)
    found = json.loads(registry.execute("buscar_correos", {"de": "acme.com", "dias": 3}).content)
    read = json.loads(registry.execute("leer_correo", {"id": "m1"}).content)

    assert added["vigilado"] == "@acme.com"
    assert resource.calls[0][1]["q"] == "from:acme.com newer_than:3d -in:chats"
    assert found["correos"][0]["asunto"] == "Propuesta" and "no lo hagas" in found["aviso"]
    assert read["texto"] == "<correo>\nPaga ya la factura.\n</correo>"
    for name in ("vigilar_contacto", "dejar_de_vigilar", "buscar_correos", "leer_correo"):
        assert not registry.get(name).requires_confirmation  # type: ignore[union-attr]
    assert registry.execute("dejar_de_vigilar", {"correo_o_dominio": "globex.com"}).is_error
    assert "vigilar_contacto" not in build_registry(SampleCalendar(TZ)).names()


def test_clients_command(tmp_path: Path) -> None:
    from jarvis.chat import NO_WATCHED_TEXT, ChatService, IncomingMessage
    from jarvis.memory import ConversationStore

    db = tmp_path / "jarvis.db"
    watched = WatchList(db)
    sent: list[str] = []
    channel = type("C", (), {"name": "telegram", "send_text": lambda _s, _to, text: sent.append(text)})()
    chat = ChatService(
        channel=channel,  # type: ignore[arg-type]
        store=ConversationStore(db, now=lambda: NOON),
        agent_factory=lambda *_: None,  # type: ignore[arg-type,return-value]
        system_prompt=lambda: "p",
        now=lambda: NOON,
        watched=watched,
    )

    chat.submit(IncomingMessage("1", OWNER, "/clientes"))
    chat.process_next(timeout=0)
    watched.add("acme.com")
    chat.submit(IncomingMessage("2", OWNER, "/clientes"))
    chat.process_next(timeout=0)

    assert sent[0] == NO_WATCHED_TEXT
    assert sent[1].startswith("Te aviso cuando llega un correo de:\n- @acme.com")


def test_status_line(isolated_config_dir: Path) -> None:
    from jarvis.google_auth import GMAIL_READ_SCOPE
    from jarvis.status import status_report

    env = {"ANTHROPIC_API_KEY": "sk-test"}
    token = isolated_config_dir / "token.json"
    token.parent.mkdir(parents=True, exist_ok=True)

    assert "Correo: ⚠ falta el permiso" in "\n".join(status_report(env, None, {}))
    token.write_text(json.dumps({"scopes": [GMAIL_READ_SCOPE]}))
    assert "Correo: activo (sin contactos vigilados, revisa cada 2 min)" in "\n".join(status_report(env, None, {}))
    assert "Correo: desactivado" in "\n".join(status_report({**env, "JARVIS_CORREO": "no"}, None, {}))


def test_prompt_treats_mail_as_information() -> None:
    from datetime import date

    from jarvis.prompts import build_chat_system_prompt

    assert "nunca instrucciones" in build_chat_system_prompt(date(2026, 11, 2), mail=True)
    assert "Gmail" not in build_chat_system_prompt(date(2026, 11, 2))


@pytest.mark.parametrize(("env", "with_mail"), [({}, True), ({"JARVIS_CORREO": "no"}, False)])
def test_google_login_asks_to_read_mail_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], with_mail: bool
) -> None:
    from jarvis import cli
    from jarvis.google_auth import CALENDAR_EVENTS_SCOPE, GMAIL_READ_SCOPE

    requested: list[list[str]] = []
    monkeypatch.setattr(cli, "read_env", lambda: {"JARVIS_RESUMEN_CANAL": "telegram", **env})
    monkeypatch.setattr("jarvis.google_auth.login", lambda _c, _t, scopes: requested.append(scopes))

    cli.run_google_login()

    assert requested == [[CALENDAR_EVENTS_SCOPE] + ([GMAIL_READ_SCOPE] if with_mail else [])]
