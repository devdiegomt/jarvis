"""Conexiones HTTPS simuladas para probar el cliente de Telegram sin red."""

import io
from typing import Any

import pytest

from jarvis.telegram import client as client_module


class FakeResponse:
    def __init__(self, status: int, body: bytes, will_close: bool = False) -> None:
        self.status = status
        self.will_close = will_close
        self._body = io.BytesIO(body)
        self._size = len(body)

    def read(self, amt: int | None = None) -> bytes:
        return self._body.read() if amt is None else self._body.read(amt)

    def isclosed(self) -> bool:  # como http.client: cerrada cuando se leyó entera
        return self._body.tell() >= self._size


class FakeConnection:
    """Responde, en orden, lo guionizado: una respuesta o una excepción por petición."""

    def __init__(self, script: list[Any]) -> None:
        self.script = script
        self.requests: list[tuple[str, str, bytes | None, dict[str, str]]] = []
        self.timeout: float | None = None
        self.sock = None
        self.closed = False
        self._pending: Any = None

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> None:
        self.requests.append((method, path, body, dict(headers or {})))
        self._pending = self.script.pop(0)

    def getresponse(self) -> FakeResponse:
        if isinstance(self._pending, BaseException):
            raise self._pending
        return self._pending

    def close(self) -> None:
        self.closed = True


def ok(result: Any = None, **kwargs: Any) -> FakeResponse:
    import json

    return FakeResponse(200, json.dumps({"ok": True, "result": result or {}}).encode(), **kwargs)


def fake_pool(monkeypatch: pytest.MonkeyPatch, script: list[Any], **pool_kwargs: Any) -> list[FakeConnection]:
    """Sustituye el pool del módulo: todas las conexiones nuevas comparten el mismo guion."""
    connections: list[FakeConnection] = []

    def connect(_host: str, _timeout: float) -> FakeConnection:
        connections.append(FakeConnection(script))
        return connections[-1]

    monkeypatch.setattr(client_module, "POOL", client_module.ConnectionPool(connect=connect, **pool_kwargs))  # type: ignore[arg-type]
    return connections
