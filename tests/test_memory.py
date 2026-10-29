from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jarvis.memory import ConversationStore

START = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
THINKING_HISTORY = [
    {"role": "user", "content": [{"type": "text", "text": "hola"}]},
    {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "", "signature": "firma-opaca=="},
            {"type": "text", "text": "¡Hola!"},
        ],
    },
]


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **kwargs: float) -> None:
        self.moment += timedelta(**kwargs)


@pytest.fixture
def clock() -> Clock:
    return Clock(START)


@pytest.fixture
def store(tmp_path: Path, clock: Clock) -> ConversationStore:
    return ConversationStore(tmp_path / "jarvis.db", now=clock)


def load(store: ConversationStore, prompt: str = "prompt-1"):  # type: ignore[no-untyped-def]
    return store.load_active("whatsapp", "573001234567", lambda: prompt)


def test_new_conversation_when_none_exists(store: ConversationStore) -> None:
    conversation = load(store)

    assert conversation.id is None
    assert conversation.messages == []
    assert conversation.system_prompt == "prompt-1"


def test_saved_conversation_is_resumed_intact(store: ConversationStore, clock: Clock) -> None:
    conversation = load(store)
    conversation.messages = THINKING_HISTORY
    store.save(conversation)

    clock.advance(hours=1)
    resumed = load(store, prompt="prompt-2")

    assert resumed.id == conversation.id
    assert resumed.messages == THINKING_HISTORY  # los bloques de razonamiento se conservan
    assert resumed.system_prompt == "prompt-1"  # el system prompt no cambia a mitad de conversación


def test_inactivity_starts_a_new_conversation(store: ConversationStore, clock: Clock) -> None:
    conversation = load(store)
    conversation.messages = THINKING_HISTORY
    store.save(conversation)

    clock.advance(hours=6)
    fresh = load(store, prompt="prompt-2")

    assert fresh.id is None
    assert fresh.messages == []
    assert fresh.system_prompt == "prompt-2"


def test_activity_extends_the_conversation(store: ConversationStore, clock: Clock) -> None:
    conversation = load(store)
    store.save(conversation)
    for _ in range(3):
        clock.advance(hours=5)
        conversation = load(store)
        store.save(conversation)

    assert load(store).id is not None


def test_close_active_forces_a_new_conversation(store: ConversationStore) -> None:
    conversation = load(store)
    store.save(conversation)

    store.close_active("whatsapp", "573001234567")

    assert load(store).id is None


def test_conversations_are_per_user(store: ConversationStore) -> None:
    conversation = load(store)
    store.save(conversation)

    assert store.load_active("whatsapp", "otro", lambda: "p").id is None


def test_mark_processed_detects_duplicates(store: ConversationStore) -> None:
    assert store.mark_processed("wamid.1")
    assert not store.mark_processed("wamid.1")
    assert store.mark_processed("wamid.2")


def test_purge_removes_old_data(store: ConversationStore, clock: Clock) -> None:
    old = load(store)
    store.save(old)
    store.mark_processed("wamid.viejo")

    clock.advance(days=31)
    recent = store.load_active("whatsapp", "otro", lambda: "p")
    store.save(recent)

    assert store.purge_old() == 1
    assert store.mark_processed("wamid.viejo")  # su registro también se borró
    assert store.load_active("whatsapp", "otro", lambda: "p").id == recent.id
