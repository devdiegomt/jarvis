"""Historial de conversaciones persistente en SQLite (hoy lo usa el chat de Telegram).

Una conversación termina tras un periodo de inactividad o cuando el usuario pide una nueva.
Nunca se recortan mensajes de una conversación en curso: el historial solo crece, porque
editarlo invalidaría los bloques de razonamiento que el modelo devuelve.
"""

import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SESSION_TIMEOUT = timedelta(hours=6)
RETENTION = timedelta(days=30)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    channel       TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    messages      TEXT NOT NULL,  -- JSON: historial en el formato de la API de Anthropic
    started_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    closed        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations (channel, user_id, updated_at);
CREATE TABLE IF NOT EXISTS processed_messages (
    message_id  TEXT PRIMARY KEY,
    received_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preferences (  -- ajustes del usuario (por ejemplo, /voz); no caducan
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    name    TEXT NOT NULL,
    value   TEXT NOT NULL,
    PRIMARY KEY (channel, user_id, name)
);
"""


@dataclass
class Conversation:
    channel: str
    user_id: str
    system_prompt: str
    started_at: datetime
    updated_at: datetime
    messages: list[dict[str, Any]] = field(default_factory=list)
    id: int | None = None  # None hasta que se guarda por primera vez


class ConversationStore:
    def __init__(
        self,
        db_path: Path,
        now: Callable[[], datetime],
        session_timeout: timedelta = SESSION_TIMEOUT,
        retention: timedelta = RETENTION,
    ) -> None:
        self._db_path = db_path
        self._now = now
        self._session_timeout = session_timeout
        self._retention = retention

    def load_active(self, channel: str, user_id: str, system_prompt: Callable[[], str]) -> Conversation:
        """La conversación en curso, o una nueva si no hay o si caducó por inactividad.

        `system_prompt` solo se usa al crear una conversación nueva: dentro de una conversación
        el system prompt no cambia, para no alterar el historial ya enviado al modelo.
        """
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT id, system_prompt, messages, started_at, updated_at FROM conversations "
                "WHERE channel = ? AND user_id = ? AND closed = 0 ORDER BY updated_at DESC LIMIT 1",
                (channel, user_id),
            ).fetchone()
        now = self._now()
        if row is not None:
            updated_at = datetime.fromisoformat(row[4])
            if now - updated_at < self._session_timeout:
                return Conversation(
                    id=row[0],
                    channel=channel,
                    user_id=user_id,
                    system_prompt=row[1],
                    messages=json.loads(row[2]),
                    started_at=datetime.fromisoformat(row[3]),
                    updated_at=updated_at,
                )
        return Conversation(channel, user_id, system_prompt(), started_at=now, updated_at=now)

    def save(self, conversation: Conversation) -> None:
        conversation.updated_at = self._now()
        messages = json.dumps(conversation.messages, ensure_ascii=False)
        with closing(self._connect()) as conn, conn:
            if conversation.id is None:
                cursor = conn.execute(
                    "INSERT INTO conversations "
                    "(channel, user_id, system_prompt, messages, started_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        conversation.channel,
                        conversation.user_id,
                        conversation.system_prompt,
                        messages,
                        _utc(conversation.started_at),
                        _utc(conversation.updated_at),
                    ),
                )
                conversation.id = cursor.lastrowid
            else:
                conn.execute(
                    "UPDATE conversations SET messages = ?, updated_at = ? WHERE id = ?",
                    (messages, _utc(conversation.updated_at), conversation.id),
                )

    def close_active(self, channel: str, user_id: str) -> None:
        """Cierra la conversación en curso; el siguiente mensaje empieza una nueva."""
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE conversations SET closed = 1 WHERE channel = ? AND user_id = ? AND closed = 0",
                (channel, user_id),
            )

    def mark_processed(self, message_id: str) -> bool:
        """Registra un mensaje entrante. Devuelve False si ya se había procesado."""
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO processed_messages (message_id, received_at) VALUES (?, ?)",
                (message_id, _utc(self._now())),
            )
        return cursor.rowcount == 1

    def get_preference(self, channel: str, user_id: str, name: str) -> str | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT value FROM preferences WHERE channel = ? AND user_id = ? AND name = ?",
                (channel, user_id, name),
            ).fetchone()
        return row[0] if row else None

    def set_preference(self, channel: str, user_id: str, name: str, value: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO preferences (channel, user_id, name, value) VALUES (?, ?, ?, ?)",
                (channel, user_id, name, value),
            )

    def purge_old(self) -> int:
        """Borra conversaciones e IDs de mensajes más antiguos que la retención."""
        cutoff = _utc(self._now() - self._retention)
        with closing(self._connect()) as conn, conn:
            deleted = conn.execute("DELETE FROM conversations WHERE updated_at < ?", (cutoff,)).rowcount
            conn.execute("DELETE FROM processed_messages WHERE received_at < ?", (cutoff,))
        return deleted

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.executescript(_SCHEMA)
        return conn


def _utc(moment: datetime) -> str:
    """Fechas en UTC para que la comparación como texto sea correcta todo el año."""
    return moment.astimezone(UTC).isoformat()
