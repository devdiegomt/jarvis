"""Memoria a largo plazo: datos duraderos sobre el usuario (SQLite).

A diferencia del historial de conversaciones (que se borra a los 30 días), los datos se guardan
hasta que el usuario los borra. Se añaden al system prompt al empezar cada conversación nueva.
"""

import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MAX_MEMORIES = 200
MAX_MEMORY_LENGTH = 300

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class MemoryLimitError(Exception):
    """La memoria está llena."""


@dataclass(frozen=True)
class Memory:
    id: int
    text: str


class MemoryStore:
    def __init__(self, db_path: Path, now: Callable[[], datetime]) -> None:
        self._db_path = db_path
        self._now = now

    def add(self, text: str) -> tuple[Memory, bool]:
        """Guarda un dato. Devuelve (dato, es_nuevo): si ya estaba igual, no se duplica."""
        existing = next((m for m in self.all() if m.text.casefold() == text.casefold()), None)
        if existing is not None:
            return existing, False
        if self.count() >= MAX_MEMORIES:
            raise MemoryLimitError(f"La memoria está llena ({MAX_MEMORIES} datos).")
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "INSERT INTO memories (text, created_at) VALUES (?, ?)",
                (text, self._now().astimezone(UTC).isoformat(timespec="seconds")),
            )
        assert cursor.lastrowid is not None
        return Memory(cursor.lastrowid, text), True

    def all(self) -> list[Memory]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT id, text FROM memories ORDER BY id").fetchall()
        return [Memory(row[0], row[1]) for row in rows]

    def count(self) -> int:
        with closing(self._connect()) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])

    def delete(self, memory_id: int) -> Memory | None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute("SELECT id, text FROM memories WHERE id = ?", (memory_id,)).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return Memory(row[0], row[1])

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.executescript(_SCHEMA)
        return conn
