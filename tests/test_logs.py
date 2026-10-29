import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from jarvis.logs import FILE_ONLY, LOG_BACKUPS, MAX_LOG_BYTES, setup_logger, tail


@pytest.fixture
def logger(request: pytest.FixtureRequest) -> logging.Logger:
    log = logging.getLogger(f"jarvis.test.{request.node.name}")
    yield log
    for handler in list(log.handlers):
        handler.close()
        log.removeHandler(handler)


def test_file_log_rotates(logger: logging.Logger, tmp_path: Path) -> None:
    setup_logger(logger, tmp_path / "logs" / "jarvis.log", console=False)

    handler = logger.handlers[0]
    assert isinstance(handler, RotatingFileHandler)
    assert handler.maxBytes == MAX_LOG_BYTES
    assert handler.backupCount == LOG_BACKUPS


def test_setup_is_idempotent(logger: logging.Logger, tmp_path: Path) -> None:
    setup_logger(logger, tmp_path / "jarvis.log", console=False)
    setup_logger(logger, tmp_path / "jarvis.log", console=False)

    assert len(logger.handlers) == 1


def test_file_only_messages_skip_the_console(
    logger: logging.Logger, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log_file = tmp_path / "jarvis.log"
    setup_logger(logger, log_file, console=True)

    logger.info("a la consola y al archivo")
    logger.error("solo al archivo", extra=FILE_ONLY)
    for handler in logger.handlers:
        handler.flush()

    console = capsys.readouterr().err
    assert "a la consola" in console and "solo al archivo" not in console
    assert "solo al archivo" in log_file.read_text(encoding="utf-8")


def test_no_console_handler_without_stderr(
    logger: logging.Logger, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "stderr", None)  # como con pythonw

    setup_logger(logger, tmp_path / "jarvis.log", console=True)

    assert [type(h) for h in logger.handlers] == [RotatingFileHandler]


def test_tail_returns_last_lines(tmp_path: Path) -> None:
    log_file = tmp_path / "jarvis.log"
    log_file.write_text("uno\ndos\ntres\n", encoding="utf-8")

    assert tail(log_file, lines=2) == ["dos", "tres"]
    assert tail(tmp_path / "no-existe.log") == []
