import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from jarvis.storage import SummaryLog


def test_records_and_detects_sent_summaries(tmp_path: Path) -> None:
    log = SummaryLog(tmp_path / "datos" / "jarvis.db")

    assert not log.was_sent(date(2026, 10, 29))
    log.record_sent(date(2026, 10, 29), datetime(2026, 10, 29, 12, 0, tzinfo=UTC))

    assert log.was_sent(date(2026, 10, 29))
    assert not log.was_sent(date(2026, 10, 30))


def test_data_survives_new_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "jarvis.db"
    SummaryLog(db_path).record_sent(date(2026, 10, 29), datetime(2026, 10, 29, 12, 0, tzinfo=UTC))

    assert SummaryLog(db_path).was_sent(date(2026, 10, 29))


def test_recording_twice_keeps_one_row(tmp_path: Path) -> None:
    db_path = tmp_path / "jarvis.db"
    log = SummaryLog(db_path)
    log.record_sent(date(2026, 10, 29), datetime(2026, 10, 29, 12, 0, tzinfo=UTC))
    log.record_sent(date(2026, 10, 29), datetime(2026, 10, 29, 13, 0, tzinfo=UTC))

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT day, sent_at FROM daily_summaries").fetchall()
    assert rows == [("2026-10-29", "2026-10-29T13:00:00+00:00")]
