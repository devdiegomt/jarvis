"""Pendientes: cosas por hacer sin hora fija, con fecha límite opcional (SQLite).

Se diferencian de los recordatorios en que no avisan a una hora: se consultan cuando el
usuario pregunta y aparecen en el resumen diario el día que vencen.
"""

import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

RETENTION = timedelta(days=30)  # los pendientes hechos se borran a los 30 días
MAX_OPEN_TASKS = 200

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    due_date   TEXT,  -- fecha local YYYY-MM-DD, o NULL si no tiene
    done       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_open ON tasks (done, due_date);
"""


class TaskLimitError(Exception):
    """Hay demasiados pendientes abiertos."""


@dataclass(frozen=True)
class Task:
    id: int
    text: str
    due_date: date | None
    done: bool


class TaskStore:
    def __init__(self, db_path: Path, now: Callable[[], datetime]) -> None:
        self._db_path = db_path
        self._now = now

    def add(self, text: str, due_date: date | None = None) -> Task:
        if len(self.open()) >= MAX_OPEN_TASKS:
            raise TaskLimitError(f"Ya hay {MAX_OPEN_TASKS} pendientes abiertos.")
        now = _utc(self._now())
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "INSERT INTO tasks (text, due_date, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (text, due_date.isoformat() if due_date else None, now, now),
            )
        assert cursor.lastrowid is not None
        return Task(cursor.lastrowid, text, due_date, done=False)

    def get(self, task_id: int) -> Task | None:
        rows = self._select("WHERE id = ?", (task_id,))
        return rows[0] if rows else None

    def open(self) -> list[Task]:
        """Pendientes abiertos: primero los que tienen fecha (los más urgentes antes), luego el resto."""
        return self._select("WHERE done = 0 ORDER BY due_date IS NULL, due_date, id", ())

    def due_by(self, day: date) -> list[Task]:
        """Pendientes abiertos que vencen `day` o antes (atrasados)."""
        return self._select("WHERE done = 0 AND due_date <= ? ORDER BY due_date, id", (day.isoformat(),))

    def complete(self, task_id: int) -> bool:
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "UPDATE tasks SET done = 1, updated_at = ? WHERE id = ? AND done = 0",
                (_utc(self._now()), task_id),
            )
        return cursor.rowcount == 1

    def delete(self, task_id: int) -> bool:
        with closing(self._connect()) as conn, conn:
            return conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,)).rowcount == 1

    def purge_old(self) -> int:
        """Borra los pendientes hechos hace más de 30 días."""
        cutoff = _utc(self._now() - RETENTION)
        with closing(self._connect()) as conn, conn:
            return conn.execute("DELETE FROM tasks WHERE done = 1 AND updated_at < ?", (cutoff,)).rowcount

    def _select(self, where: str, params: tuple[Any, ...]) -> list[Task]:
        with closing(self._connect()) as conn:
            rows = conn.execute(f"SELECT id, text, due_date, done FROM tasks {where}", params).fetchall()
        return [Task(row[0], row[1], date.fromisoformat(row[2]) if row[2] else None, bool(row[3])) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.executescript(_SCHEMA)
        return conn


def _utc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")
