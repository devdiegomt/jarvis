"""Contactos vigilados: de quién avisar cuando llega un correo (una dirección o todo un dominio).

Se guardan solo en el equipo (SQLite) y se manejan hablando con JARVIS o con /clientes.
"""

import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

MAX_WATCHED = 100

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watched_senders (
    pattern    TEXT PRIMARY KEY,  -- laura@acme.com o @acme.com
    created_at TEXT NOT NULL
);
"""
_EMAIL = re.compile(r"[a-z0-9._%+'-]+@[a-z0-9.-]+\.[a-z]{2,}")
_DOMAIN = re.compile(r"@[a-z0-9.-]+\.[a-z]{2,}")


def normalize_pattern(value: str) -> str:
    """`Laura@Acme.com` → `laura@acme.com`; `acme.com` o `@acme.com` → `@acme.com`."""
    pattern = value.strip().lower()
    if "@" not in pattern:
        pattern = f"@{pattern}"
    if not (_EMAIL.fullmatch(pattern) or _DOMAIN.fullmatch(pattern)):
        raise ValueError(
            f"«{value}» no es un correo ni un dominio válido (por ejemplo, laura@acme.com o acme.com)."
        )
    return pattern


class WatchList:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def add(self, value: str) -> tuple[str, bool]:
        """Agrega un correo o dominio. Devuelve (patrón, es_nuevo)."""
        pattern = normalize_pattern(value)
        if pattern in self.all():
            return pattern, False
        if len(self.all()) >= MAX_WATCHED:
            raise ValueError(f"Ya hay {MAX_WATCHED} contactos vigilados; quita alguno primero.")
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO watched_senders (pattern, created_at) VALUES (?, ?)",
                (pattern, datetime.now(UTC).isoformat(timespec="seconds")),
            )
        return pattern, True

    def remove(self, value: str) -> str | None:
        pattern = normalize_pattern(value)
        with closing(self._connect()) as conn, conn:
            deleted = conn.execute("DELETE FROM watched_senders WHERE pattern = ?", (pattern,)).rowcount
        return pattern if deleted else None

    def all(self) -> list[str]:
        with closing(self._connect()) as conn:
            return [row[0] for row in conn.execute("SELECT pattern FROM watched_senders ORDER BY pattern")]

    def matches(self, sender_email: str) -> bool:
        return self.watched_since(sender_email) is not None

    def watched_since(self, sender_email: str) -> datetime | None:
        """Desde cuándo se vigila a este remitente (None si no se vigila): no se avisa de lo anterior."""
        sender = sender_email.lower()
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT pattern, created_at FROM watched_senders").fetchall()
        times = [
            datetime.fromisoformat(created)
            for pattern, created in rows
            if sender == pattern or (pattern.startswith("@") and sender.endswith(pattern))
        ]
        return min(times) if times else None

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.executescript(_SCHEMA)
        return conn
