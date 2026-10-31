import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from jarvis.agenda import SampleCalendar
from jarvis.long_term_memory import MemoryLimitError, MemoryStore
from jarvis.prompts import build_chat_system_prompt, build_system_prompt
from jarvis.tools import build_registry

NOW = datetime(2026, 10, 30, 13, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "jarvis.db", now=lambda: NOW)


# --- Almacenamiento ---------------------------------------------------------


def test_add_list_and_delete(store: MemoryStore) -> None:
    laura, is_new = store.add("Su socia se llama Laura.")
    store.add("Prefiere reuniones por la mañana.")

    assert is_new
    assert [m.text for m in store.all()] == ["Su socia se llama Laura.", "Prefiere reuniones por la mañana."]
    assert store.delete(laura.id) == laura
    assert store.delete(laura.id) is None
    assert store.count() == 1


def test_same_memory_is_not_duplicated(store: MemoryStore) -> None:
    first, _ = store.add("Su socia se llama Laura.")
    again, is_new = store.add("su socia se llama laura.")

    assert again == first and not is_new
    assert store.count() == 1


def test_memory_limit(store: MemoryStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jarvis.long_term_memory.MAX_MEMORIES", 1)
    store.add("a")

    with pytest.raises(MemoryLimitError):
        store.add("b")


def test_memories_never_expire(store: MemoryStore, tmp_path: Path) -> None:
    store.add("Su socia se llama Laura.")
    years_later = MemoryStore(tmp_path / "jarvis.db", now=lambda: datetime(2030, 1, 1, tzinfo=UTC))

    assert [m.text for m in years_later.all()] == ["Su socia se llama Laura."]


# --- Tools ------------------------------------------------------------------


def run(store: MemoryStore, tool: str, **tool_input: Any):  # type: ignore[no-untyped-def]
    return build_registry(SampleCalendar(UTC), memories=store).execute(tool, tool_input)


def test_memory_tools_are_registered_and_need_no_confirmation(store: MemoryStore) -> None:
    registry = build_registry(SampleCalendar(UTC), memories=store)
    names = {"recordar_dato", "listar_datos", "olvidar_dato"}

    assert names <= set(registry.names())
    assert not any(registry.get(name).requires_confirmation for name in names)  # type: ignore[union-attr]
    assert "recordar_dato" not in build_registry(SampleCalendar(UTC)).names()


def test_remember_list_and_forget(store: MemoryStore) -> None:
    remembered = json.loads(run(store, "recordar_dato", dato="  Su socia   se llama Laura. ").content)
    again = json.loads(run(store, "recordar_dato", dato="Su socia se llama Laura.").content)
    listed = json.loads(run(store, "listar_datos").content)
    forgotten = json.loads(run(store, "olvidar_dato", id=remembered["recordado"]["id"]).content)

    assert remembered["recordado"]["dato"] == "Su socia se llama Laura."
    assert "ya_lo_sabias" in again
    assert listed["datos"] == [remembered["recordado"]]
    assert forgotten["olvidado"]["dato"] == "Su socia se llama Laura."
    assert "Aún no recuerdas nada" in run(store, "listar_datos").content
    assert run(store, "olvidar_dato", id=99).is_error


@pytest.mark.parametrize(
    ("dato", "expected"),
    [
        ("   ", "vacío"),
        ("x" * 301, "300 caracteres"),
        ("Su tarjeta es 4111 1111 1111 1111", "números largos"),
        ("Su cuenta es 123456789012", "números largos"),
    ],
)
def test_remember_validation(store: MemoryStore, dato: str, expected: str) -> None:
    result = run(store, "recordar_dato", dato=dato)

    assert result.is_error and expected in result.content
    assert store.count() == 0


def test_short_numbers_are_fine(store: MemoryStore) -> None:
    assert not run(store, "recordar_dato", dato="Su oficina está en la calle 93 #11-27").is_error


# --- System prompt ----------------------------------------------------------


def test_memories_go_into_the_system_prompt_with_their_ids(store: MemoryStore) -> None:
    store.add("Su socia se llama Laura.")
    store.add("Prefiere reuniones por la mañana.")

    prompt = build_chat_system_prompt(date(2026, 10, 30), store.all())

    assert "<memoria>\n- [1] Su socia se llama Laura.\n- [2] Prefiere reuniones por la mañana.\n</memoria>" in prompt
    assert "recordar_dato" in prompt


def test_prompt_without_memories() -> None:
    prompt = build_system_prompt(date(2026, 10, 30))

    assert "Aún no recuerdas nada del usuario" in prompt
    assert "<memoria>" not in prompt
