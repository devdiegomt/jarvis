"""Dinero: gastos, ingresos y cuentas por cobrar a clientes (SQLite, solo en el equipo).

Los montos se guardan como enteros en centavos (sin errores de redondeo) y los totales se calculan
en código: el modelo entiende los mensajes ("gasté 25 mil en almuerzo"), pero no suma.
"""

import sqlite3
from collections import defaultdict
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

MAX_AMOUNT = Decimal("1000000000000")  # un billón: más que eso es casi seguro un error
NO_DECIMALS = {"COP", "CLP", "JPY", "PYG"}  # monedas que en la práctica no usan centavos

_SCHEMA = """
CREATE TABLE IF NOT EXISTS money_moves (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,     -- gasto | ingreso
    cents       INTEGER NOT NULL,  -- monto en centavos (siempre positivo)
    currency    TEXT NOT NULL,
    category    TEXT NOT NULL,
    description TEXT NOT NULL,
    day         TEXT NOT NULL,     -- fecha local YYYY-MM-DD
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_money_moves_day ON money_moves (day);
CREATE TABLE IF NOT EXISTS receivables (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client      TEXT NOT NULL,
    cents       INTEGER NOT NULL,
    currency    TEXT NOT NULL,
    description TEXT NOT NULL,
    due_date    TEXT,              -- fecha local YYYY-MM-DD, o NULL
    paid_on     TEXT,              -- fecha local en que se pagó, o NULL si sigue pendiente
    created_at  TEXT NOT NULL
);
"""


class MoneyError(ValueError):
    """Dato inválido. El mensaje está pensado para el modelo y el usuario."""


@dataclass(frozen=True)
class Move:
    id: int
    kind: str  # gasto | ingreso
    amount: Decimal
    currency: str
    category: str
    description: str
    day: date


@dataclass(frozen=True)
class Receivable:
    id: int
    client: str
    amount: Decimal
    currency: str
    description: str
    due_date: date | None
    paid_on: date | None

    def overdue_days(self, today: date) -> int:
        """Días de atraso (0 si no venció o ya se pagó)."""
        if self.paid_on is not None or self.due_date is None or self.due_date >= today:
            return 0
        return (today - self.due_date).days


@dataclass(frozen=True)
class MonthSummary:
    year: int
    month: int
    currency: str
    expenses: Decimal
    income: Decimal
    by_category: list[tuple[str, Decimal]]  # gastos por categoría, de mayor a menor
    moves: int
    other_currencies: int  # movimientos en otra moneda (no se suman)

    @property
    def balance(self) -> Decimal:
        return self.income - self.expenses


class MoneyStore:
    def __init__(self, db_path: Path, now: Callable[[], datetime]) -> None:
        self._db_path = db_path
        self._now = now

    # --- Movimientos ------------------------------------------------------------

    def add_move(
        self, kind: str, amount: Decimal, currency: str, category: str, description: str, day: date
    ) -> Move:
        if kind not in ("gasto", "ingreso"):
            raise MoneyError("El tipo debe ser «gasto» o «ingreso».")
        cents = _to_cents(amount)
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "INSERT INTO money_moves (kind, cents, currency, category, description, day, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (kind, cents, currency, category, description, day.isoformat(), self._stamp()),
            )
        assert cursor.lastrowid is not None
        return Move(cursor.lastrowid, kind, _from_cents(cents), currency, category, description, day)

    def get_move(self, move_id: int) -> Move | None:
        rows = self._moves("WHERE id = ?", (move_id,))
        return rows[0] if rows else None

    def delete_move(self, move_id: int) -> bool:
        with closing(self._connect()) as conn, conn:
            return conn.execute("DELETE FROM money_moves WHERE id = ?", (move_id,)).rowcount > 0

    def moves_between(self, start: date, end: date) -> list[Move]:
        """Movimientos entre dos fechas (incluidas), del más reciente al más antiguo."""
        return self._moves(
            "WHERE day BETWEEN ? AND ? ORDER BY day DESC, id DESC", (start.isoformat(), end.isoformat())
        )

    def month_summary(self, year: int, month: int, currency: str) -> MonthSummary:
        start = date(year, month, 1)
        end = date(year + month // 12, month % 12 + 1, 1)
        moves = self._moves("WHERE day >= ? AND day < ?", (start.isoformat(), end.isoformat()))
        totals: dict[str, Decimal] = defaultdict(Decimal)
        expenses = income = Decimal(0)
        same = [m for m in moves if m.currency == currency]
        for move in same:
            if move.kind == "gasto":
                expenses += move.amount
                totals[move.category] += move.amount
            else:
                income += move.amount
        by_category = sorted(totals.items(), key=lambda item: item[1], reverse=True)
        others = len(moves) - len(same)
        return MonthSummary(year, month, currency, expenses, income, by_category, len(moves), others)

    # --- Cuentas por cobrar -----------------------------------------------------

    def add_receivable(
        self, client: str, amount: Decimal, currency: str, description: str, due_date: date | None
    ) -> Receivable:
        cents = _to_cents(amount)
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "INSERT INTO receivables (client, cents, currency, description, due_date, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (client, cents, currency, description, due_date.isoformat() if due_date else None, self._stamp()),
            )
        assert cursor.lastrowid is not None
        return Receivable(cursor.lastrowid, client, _from_cents(cents), currency, description, due_date, None)

    def get_receivable(self, receivable_id: int) -> Receivable | None:
        rows = self._receivables("WHERE id = ?", (receivable_id,))
        return rows[0] if rows else None

    def open_receivables(self) -> list[Receivable]:
        """Cobros sin pagar: primero los que vencen antes; los que no tienen fecha, al final."""
        return self._receivables("WHERE paid_on IS NULL ORDER BY due_date IS NULL, due_date, id", ())

    def paid_receivables(self, since: date) -> list[Receivable]:
        return self._receivables("WHERE paid_on >= ? ORDER BY paid_on DESC", (since.isoformat(),))

    def mark_paid(self, receivable_id: int, day: date) -> bool:
        with closing(self._connect()) as conn, conn:
            return (
                conn.execute(
                    "UPDATE receivables SET paid_on = ? WHERE id = ? AND paid_on IS NULL",
                    (day.isoformat(), receivable_id),
                ).rowcount
                > 0
            )

    def delete_receivable(self, receivable_id: int) -> bool:
        with closing(self._connect()) as conn, conn:
            return conn.execute("DELETE FROM receivables WHERE id = ?", (receivable_id,)).rowcount > 0

    # --- SQLite -------------------------------------------------------------------

    def _moves(self, where: str, params: tuple[Any, ...]) -> list[Move]:
        if not self._db_path.exists():
            return []
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT id, kind, cents, currency, category, description, day FROM money_moves {where}", params
            ).fetchall()
        return [Move(r[0], r[1], _from_cents(r[2]), r[3], r[4], r[5], date.fromisoformat(r[6])) for r in rows]

    def _receivables(self, where: str, params: tuple[Any, ...]) -> list[Receivable]:
        if not self._db_path.exists():
            return []
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT id, client, cents, currency, description, due_date, paid_on FROM receivables {where}",
                params,
            ).fetchall()
        return [
            Receivable(r[0], r[1], _from_cents(r[2]), r[3], r[4], _optional_date(r[5]), _optional_date(r[6]))
            for r in rows
        ]

    def _stamp(self) -> str:
        return self._now().astimezone(UTC).isoformat(timespec="seconds")

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.executescript(_SCHEMA)
        return conn


def parse_amount(value: Any) -> Decimal:
    """Monto positivo a partir de un número (lo que manda el modelo)."""
    try:
        amount = Decimal(str(value))
    except ArithmeticError:
        raise MoneyError(f"«{value}» no es un monto válido: usa un número, por ejemplo 25000.") from None
    if not amount.is_finite() or amount <= 0:
        raise MoneyError("El monto debe ser un número mayor que cero.")
    if amount >= MAX_AMOUNT:
        raise MoneyError("El monto es demasiado grande: revisa los ceros.")
    return amount


def format_money(amount: Decimal, currency: str) -> str:
    """Como se escribe en Colombia: «$25.000» o «$1.234,50 USD»."""
    decimals = 0 if currency in NO_DECIMALS else 2
    rounded = amount.quantize(Decimal(1) if decimals == 0 else Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = f"{rounded:,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"${text}" if currency == "COP" else f"${text} {currency}"


def _to_cents(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _from_cents(cents: int) -> Decimal:
    return (Decimal(cents) / 100).quantize(Decimal("0.01"))


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None
