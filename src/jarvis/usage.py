"""Consumo de la API de Anthropic: tokens, búsquedas y costo estimado, para saber cuánto cuesta JARVIS.

Solo se guardan números (nunca contenido) en `jarvis.db`. El costo se estima con los precios públicos
por millón de tokens; si el modelo no está en la tabla, se muestran solo los tokens.
"""

import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

RETENTION = timedelta(days=400)
WEB_SEARCH_PRICE = 10 / 1000  # USD por búsqueda en internet ($10 por cada 1.000)


@dataclass(frozen=True)
class ModelPrice:
    """USD por millón de tokens."""

    input: float
    output: float
    cache_read: float
    cache_write: float  # escritura en caché de 5 minutos (1,25 veces la entrada)


PRICES = {
    "claude-sonnet-5-5": ModelPrice(2.00, 10.00, 0.20, 2.50),
    "claude-sonnet-5": ModelPrice(2.00, 10.00, 0.20, 2.50),
    "claude-opus-5-5": ModelPrice(4.00, 20.00, 0.20, 5.00),
    "claude-opus-5": ModelPrice(5.00, 25.00, 0.50, 6.25),
    "claude-haiku-5-5": ModelPrice(0.10, 0.50, 0.01, 0.125),
    "claude-fable-5-1": ModelPrice(10.00, 50.00, 0.25, 12.50),
}


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0  # sin caché (precio completo)
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    web_searches: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.output_tokens + other.output_tokens,
            self.web_searches + other.web_searches,
        )

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_write_tokens + self.cache_read_tokens

    @property
    def cache_share(self) -> float:
        """Fracción de la entrada que salió de la caché (0 a 1)."""
        return self.cache_read_tokens / self.total_input if self.total_input else 0.0


def usage_from_response(response: Any) -> Usage:
    """Lee `response.usage` de la API (tolerante: los campos ausentes cuentan como 0)."""
    usage = getattr(response, "usage", None)

    def field(source: Any, name: str) -> int:
        return int(getattr(source, name, 0) or 0)

    server = getattr(usage, "server_tool_use", None)
    return Usage(
        input_tokens=field(usage, "input_tokens"),
        cache_write_tokens=field(usage, "cache_creation_input_tokens"),
        cache_read_tokens=field(usage, "cache_read_input_tokens"),
        output_tokens=field(usage, "output_tokens"),
        web_searches=field(server, "web_search_requests"),
    )


def estimate_cost(model: str, usage: Usage) -> float | None:
    """Costo en USD, o None si no se conoce el precio del modelo."""
    price = PRICES.get(model)
    if price is None:
        return None
    tokens = (
        usage.input_tokens * price.input
        + usage.cache_write_tokens * price.cache_write
        + usage.cache_read_tokens * price.cache_read
        + usage.output_tokens * price.output
    )
    return tokens / 1_000_000 + usage.web_searches * WEB_SEARCH_PRICE


def describe_usage(model: str, usage: Usage) -> str:
    """Para el registro: tokens, caché, búsquedas y costo (sin contenido)."""
    text = (
        f"{_thousands(usage.total_input)} tokens de entrada ({_thousands(usage.cache_read_tokens)} de caché), "
        f"{_thousands(usage.output_tokens)} de salida"
    )
    if usage.web_searches:
        text += f", {usage.web_searches} búsqueda(s)"
    cost = estimate_cost(model, usage)
    return text + (f" ≈ {format_usd(cost, precise=True)}" if cost is not None else "")


def _thousands(number: int) -> str:
    """12345 → «12.345», como se escribe en español."""
    return f"{number:,}".replace(",", ".")


def format_usd(amount: float, precise: bool = False) -> str:
    """`precise`: con 4 decimales (para el costo de una sola respuesta, que suele ser de centavos)."""
    if precise or amount < 0.01:
        return f"${amount:.4f}".replace(".", ",")
    return f"${amount:.2f}".replace(".", ",")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_usage (
    id          INTEGER PRIMARY KEY,
    at          TEXT NOT NULL,      -- UTC
    source      TEXT NOT NULL,      -- telegram, pc, consola, resumen…
    model       TEXT NOT NULL,
    input       INTEGER NOT NULL,
    cache_write INTEGER NOT NULL,
    cache_read  INTEGER NOT NULL,
    output      INTEGER NOT NULL,
    searches    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_api_usage_at ON api_usage (at);
"""


@dataclass(frozen=True)
class Spending:
    usage: Usage
    cost: float | None  # None si algún modelo no tiene precio conocido
    requests: int  # respuestas (cada una puede incluir varias llamadas a la API)


class UsageLog:
    """Registro del consumo por respuesta (solo números) en `jarvis.db`."""

    def __init__(self, db_path: Path, now: Callable[[], datetime]) -> None:
        self._db_path = db_path
        self._now = now

    def record(self, source: str, model: str, usage: Usage) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO api_usage (at, source, model, input, cache_write, cache_read, output, searches) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._now().astimezone(UTC).isoformat(timespec="seconds"),
                    source,
                    model,
                    usage.input_tokens,
                    usage.cache_write_tokens,
                    usage.cache_read_tokens,
                    usage.output_tokens,
                    usage.web_searches,
                ),
            )

    def since(self, start: datetime) -> Spending:
        """Consumo desde `start` (incluido)."""
        if not self._db_path.exists():
            return Spending(Usage(), 0.0, 0)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT model, SUM(input), SUM(cache_write), SUM(cache_read), SUM(output), SUM(searches), "
                "COUNT(*) FROM api_usage WHERE at >= ? GROUP BY model",
                (start.astimezone(UTC).isoformat(timespec="seconds"),),
            ).fetchall()
        total, cost, requests = Usage(), 0.0, 0
        for model, *counts, count in rows:
            usage = Usage(*(int(value) for value in counts))
            total += usage
            requests += count
            model_cost = estimate_cost(model, usage)
            cost = None if cost is None or model_cost is None else cost + model_cost
        return Spending(total, cost, requests)

    def purge_old(self) -> int:
        cutoff = (self._now() - RETENTION).astimezone(UTC).isoformat(timespec="seconds")
        with closing(self._connect()) as conn, conn:
            return conn.execute("DELETE FROM api_usage WHERE at < ?", (cutoff,)).rowcount

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.executescript(_SCHEMA)
        return conn


def spending_periods(now: datetime, timezone: tzinfo) -> list[tuple[str, datetime]]:
    """Hoy, los últimos 7 días y el mes en curso, en hora local."""
    local = now.astimezone(timezone)
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return [
        ("Hoy", today),
        ("Últimos 7 días", today - timedelta(days=6)),
        ("Este mes", today.replace(day=1)),
    ]


def spending_text(log: UsageLog, now: datetime, timezone: tzinfo) -> str:
    """Para `/gasto` y `estado`: costo estimado por periodo."""
    lines = ["💸 Gasto estimado en Claude (precios públicos de la API):"]
    for label, start in spending_periods(now, timezone):
        spent = log.since(start)
        lines.append(f"- {label}: {_describe_spending(spent)}")
    month = log.since(spending_periods(now, timezone)[2][1])
    if month.usage.total_input:
        share = month.usage.cache_share
        lines.append(f"De la entrada de este mes, {share:.0%} salió de la caché (cuesta 10 %).")
    return "\n".join(lines)


def _describe_spending(spent: Spending) -> str:
    if not spent.requests:
        return "nada"
    answers = f"{spent.requests} {'respuesta' if spent.requests == 1 else 'respuestas'}"
    searches = f", {spent.usage.web_searches} búsqueda(s)" if spent.usage.web_searches else ""
    if spent.cost is None:
        tokens = _thousands(spent.usage.total_input + spent.usage.output_tokens)
        return f"{tokens} tokens ({answers}{searches}; sin precio para el modelo)"
    return f"{format_usd(spent.cost)} ({answers}{searches})"
