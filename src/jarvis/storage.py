"""Persistencia local en SQLite.

Solo se guardan metadatos (qué día se envió el resumen y cuándo), nunca el contenido.
"""

import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_summaries (
    day     TEXT PRIMARY KEY,  -- fecha del resumen, YYYY-MM-DD
    sent_at TEXT NOT NULL      -- momento del envío, ISO 8601 con zona horaria
)
"""


class SummaryLog:
    """Registro de resúmenes diarios enviados, para no enviar dos el mismo día."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def was_sent(self, day: date) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT 1 FROM daily_summaries WHERE day = ?", (day.isoformat(),)).fetchone()
        return row is not None

    def record_sent(self, day: date, sent_at: datetime) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO daily_summaries (day, sent_at) VALUES (?, ?)",
                (day.isoformat(), sent_at.isoformat()),
            )

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute(_SCHEMA)
        return conn
