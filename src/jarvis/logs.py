"""Registros de ejecución: archivos rotativos y, si hay consola, también en pantalla.

Los registros solo contienen resultados, IDs y tipos de error, nunca el texto de los mensajes.
"""

import logging
import sys
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

MAX_LOG_BYTES = 1_000_000
LOG_BACKUPS = 3  # además del archivo actual: hasta ~4 MB por registro
_FORMAT = "%(asctime)s %(levelname)s %(message)s"

# `logger.error(msg, extra=FILE_ONLY)`: solo al archivo, cuando el mensaje ya se muestra con print.
FILE_ONLY = {"file_only": True}


def _not_file_only(record: logging.LogRecord) -> bool:
    return not getattr(record, "file_only", False)


def setup_logger(logger: logging.Logger, log_file: Path, console: bool) -> None:
    """Configura `logger` para escribir en `log_file` (rotativo) y opcionalmente en consola.

    Con `pythonw` (tareas programadas) no hay consola: `sys.stderr` es None y se omite.
    """
    if any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers):
        return
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(_FORMAT)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(log_file, maxBytes=MAX_LOG_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8")
    ]
    if console and sys.stderr is not None:
        console_handler = logging.StreamHandler()
        console_handler.addFilter(_not_file_only)
        handlers.append(console_handler)
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def tail(log_file: Path, lines: int = 5) -> list[str]:
    """Últimas líneas de un registro (vacío si no existe)."""
    if not log_file.exists():
        return []
    with log_file.open(encoding="utf-8", errors="replace") as file:
        return [line.rstrip("\n") for line in deque(file, maxlen=lines)]
