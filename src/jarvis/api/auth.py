"""Clave de la API: se genera una vez, se muestra una sola vez y en el equipo solo queda su huella."""

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path

KEY_BYTES = 32
MAX_FAILURES = 5  # intentos fallidos seguidos antes de pausar
FAILURE_WINDOW_SECONDS = 10 * 60
LOCKOUT_SECONDS = 60


def generate_key(key_file: Path) -> str:
    """Crea una clave nueva (la anterior deja de servir) y guarda solo su huella."""
    key = secrets.token_urlsafe(KEY_BYTES)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(_fingerprint(key) + "\n", encoding="utf-8")
    try:
        os.chmod(key_file, 0o600)  # solo el usuario (en Windows no aplica, y no hace falta)
    except OSError:
        pass
    return key


def has_key(key_file: Path) -> bool:
    return key_file.exists() and bool(key_file.read_text(encoding="utf-8").strip())


class KeyChecker:
    """Comprueba la clave en tiempo constante y frena los intentos fallidos repetidos."""

    def __init__(self, key_file: Path, clock: Callable[[], float] = time.monotonic) -> None:
        self._key_file = key_file
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: list[float] = []
        self._locked_until = 0.0

    def locked(self) -> bool:
        with self._lock:
            return self._clock() < self._locked_until

    def check(self, provided: str | None) -> bool:
        """True si la clave es la correcta. Cada fallo cuenta para la pausa."""
        expected = self._key_file.read_text(encoding="utf-8").strip() if self._key_file.exists() else ""
        valid = bool(expected and provided) and hmac.compare_digest(_fingerprint(provided or ""), expected)
        with self._lock:
            now = self._clock()
            if valid:
                self._failures.clear()
                return True
            self._failures = [t for t in self._failures if now - t < FAILURE_WINDOW_SECONDS] + [now]
            if len(self._failures) >= MAX_FAILURES:
                self._locked_until = now + LOCKOUT_SECONDS
                self._failures.clear()
            return False


def _fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
