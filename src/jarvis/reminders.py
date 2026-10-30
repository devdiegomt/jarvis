"""Recordatorios: almacenamiento en SQLite (la entrega está en `reminder_delivery.py`).

Estados de un recordatorio:
- `pending`: aún no se ha enviado (o se pospuso).
- `sent`: se envió al usuario.
- `done`: el usuario lo marcó como hecho.
- `cancelled`: se canceló antes de enviarse.
"""

import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

RETENTION = timedelta(days=30)
SNOOZE_MINUTES = 10

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    due_at     TEXT NOT NULL,  -- UTC, ISO 8601
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders (status, due_at);
"""


@dataclass(frozen=True)
class Reminder:
    id: int
    text: str
    due_at: datetime  # con zona horaria (UTC al leer de la base de datos)
    status: str


class ReminderStore:
    def __init__(self, db_path: Path, now: Callable[[], datetime]) -> None:
        self._db_path = db_path
        self._now = now

    def create(self, text: str, due_at: datetime) -> Reminder:
        now = _utc(self._now())
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "INSERT INTO reminders (text, due_at, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (text, _utc(due_at), now, now),
            )
        assert cursor.lastrowid is not None
        return Reminder(cursor.lastrowid, text, datetime.fromisoformat(_utc(due_at)), "pending")

    def get(self, reminder_id: int) -> Reminder | None:
        rows = self._select("WHERE id = ?", (reminder_id,))
        return rows[0] if rows else None

    def pending(self) -> list[Reminder]:
        return self._select("WHERE status = 'pending' ORDER BY due_at", ())

    def due(self) -> list[Reminder]:
        """Pendientes cuya hora ya llegó, del más antiguo al más reciente."""
        return self._select(
            "WHERE status = 'pending' AND due_at <= ? ORDER BY due_at", (_utc(self._now()),)
        )

    def cancel(self, reminder_id: int) -> bool:
        return self._set_status(reminder_id, "cancelled", only_if="pending")

    def mark_sent(self, reminder_id: int) -> bool:
        return self._set_status(reminder_id, "sent", only_if="pending")

    def mark_done(self, reminder_id: int) -> bool:
        return self._set_status(reminder_id, "done", only_if="sent")

    def snooze(self, reminder_id: int, minutes: int = SNOOZE_MINUTES) -> Reminder | None:
        """Vuelve a programar un recordatorio enviado para dentro de `minutes` minutos."""
        due_at = self._now() + timedelta(minutes=minutes)
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "UPDATE reminders SET status = 'pending', due_at = ?, updated_at = ? "
                "WHERE id = ? AND status = 'sent'",
                (_utc(due_at), _utc(self._now()), reminder_id),
            )
        return self.get(reminder_id) if cursor.rowcount == 1 else None

    def purge_old(self) -> int:
        """Borra los recordatorios ya cerrados (enviados, hechos o cancelados) hace más de 30 días."""
        cutoff = _utc(self._now() - RETENTION)
        with closing(self._connect()) as conn, conn:
            return conn.execute(
                "DELETE FROM reminders WHERE status != 'pending' AND updated_at < ?", (cutoff,)
            ).rowcount

    def _set_status(self, reminder_id: int, status: str, only_if: str) -> bool:
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "UPDATE reminders SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                (status, _utc(self._now()), reminder_id, only_if),
            )
        return cursor.rowcount == 1

    def _select(self, where: str, params: tuple[Any, ...]) -> list[Reminder]:
        with closing(self._connect()) as conn:
            query = f"SELECT id, text, due_at, status FROM reminders {where}"
            rows = conn.execute(query, params).fetchall()
        return [Reminder(row[0], row[1], datetime.fromisoformat(row[2]), row[3]) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.executescript(_SCHEMA)
        return conn


def _utc(moment: datetime) -> str:
    """Fechas en UTC para que la comparación como texto sea correcta todo el año."""
    return moment.astimezone(UTC).isoformat(timespec="seconds")
