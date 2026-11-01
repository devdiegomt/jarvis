"""Textos de dinero armados en código, sin IA: `/dinero`, `/cobros`, `/trm`, avisos de cobro y CSV."""

import csv
import io
from datetime import date, timedelta
from decimal import Decimal

from jarvis.dates import MONTHS
from jarvis.money import MoneyStore, Receivable, format_money
from jarvis.trm import TrmError, TrmService

NO_RECEIVABLES_TEXT = "Nadie te debe nada. Dime, por ejemplo, «Acme me debe 3 millones, vence el 15»."
MAX_CATEGORIES_SHOWN = 8
EXAMPLE = "«gasté 25 mil en almuerzo»"


def month_text(store: MoneyStore, today: date, currency: str) -> str:
    """El mes en curso: gastos por categoría, ingresos y balance, comparado con el mes anterior."""
    summary = store.month_summary(today.year, today.month, currency)
    title = f"💰 {MONTHS[today.month - 1].capitalize()} {today.year}"
    if not summary.moves:
        return f"{title}: todavía no has registrado movimientos. Dime, por ejemplo, {EXAMPLE}."
    lines = [title, f"Gastos: {format_money(summary.expenses, currency)}"]
    for category, amount in summary.by_category[:MAX_CATEGORIES_SHOWN]:
        lines.append(f"- {category}: {format_money(amount, currency)}")
    others = summary.by_category[MAX_CATEGORIES_SHOWN:]
    if others:
        lines.append(f"- otras: {format_money(sum((a for _, a in others), Decimal(0)), currency)}")
    lines.append(f"Ingresos: {format_money(summary.income, currency)}")
    sign = "-" if summary.balance < 0 else ""
    lines.append(f"Balance: {sign}{format_money(abs(summary.balance), currency)}")

    previous_month = date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1)
    previous = store.month_summary(previous_month.year, previous_month.month, currency)
    if previous.expenses:
        change = (summary.expenses - previous.expenses) / previous.expenses
        word = "más" if change >= 0 else "menos"
        lines.append(
            f"Llevas {abs(change):.0%} {word} de gastos que en todo {MONTHS[previous_month.month - 1]} "
            f"({format_money(previous.expenses, currency)})."
        )
    if summary.other_currencies:
        lines.append(f"({summary.other_currencies} movimiento(s) en otra moneda no están en estos totales.)")
    return "\n".join(lines)


def receivables_text(store: MoneyStore, today: date) -> str:
    """Qué te deben: vencidos primero."""
    pending = store.open_receivables()
    if not pending:
        return NO_RECEIVABLES_TEXT
    pending.sort(key=lambda r: (-r.overdue_days(today), r.due_date or date.max))
    totals: dict[str, Decimal] = {}
    for receivable in pending:
        totals[receivable.currency] = totals.get(receivable.currency, Decimal(0)) + receivable.amount
    total = " + ".join(format_money(amount, currency) for currency, amount in totals.items())
    lines = [f"🧾 Te deben {total}:"]
    lines += [f"- {receivable_line(r, today)}" for r in pending]
    return "\n".join(lines)


def receivable_line(receivable: Receivable, today: date) -> str:
    """Por ejemplo: «Acme: $3.000.000 (factura 12) · vencido hace 3 días»."""
    text = f"{receivable.client}: {format_money(receivable.amount, receivable.currency)}"
    if receivable.description:
        text += f" ({receivable.description})"
    due = receivable.due_date
    late = receivable.overdue_days(today)
    if late:
        text += f" · vencido hace {late} {'día' if late == 1 else 'días'}"
    elif due == today:
        text += " · vence hoy"
    elif due is not None:
        text += f" · vence el {due:%d/%m}"
    return text


def due_receivables(store: MoneyStore, today: date) -> list[Receivable]:
    """Cobros que vencen hoy o ya vencieron (para `/hoy` y el resumen de la mañana)."""
    return [r for r in store.open_receivables() if r.due_date is not None and r.due_date <= today]


def receivable_alert(receivable: Receivable, today: date) -> str:
    """Aviso de Telegram para un cobro que vence hoy o sigue sin pagar."""
    amount = format_money(receivable.amount, receivable.currency)
    detail = f" ({receivable.description})" if receivable.description else ""
    late = receivable.overdue_days(today)
    if late:
        weeks = late // 7
        when = f"hace {weeks} {'semana' if weeks == 1 else 'semanas'}" if late % 7 == 0 else f"hace {late} días"
        return f"⚠️ {receivable.client} sigue sin pagarte {amount}{detail}: venció {when}."
    return f"💰 Hoy vence el cobro a {receivable.client}: {amount}{detail}."


def trm_text(trm: TrmService, today: date) -> str:
    try:
        rate = trm.on(today)
    except TrmError as exc:
        return str(exc)
    return f"💵 {rate.line} (vigente desde el {rate.valid_from:%d/%m/%Y}). Fuente: Superintendencia Financiera."


def moves_csv(store: MoneyStore, start: date, end: date) -> str:
    """CSV de los movimientos (para el contador o una hoja de cálculo), del más antiguo al más reciente."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["fecha", "tipo", "categoria", "descripcion", "monto", "moneda"])
    for move in reversed(store.moves_between(start, end)):
        row = [move.day.isoformat(), move.kind, move.category, move.description, str(move.amount), move.currency]
        writer.writerow(row)
    return buffer.getvalue()


def export_period(today: date, month: str | None, year: str | None) -> tuple[date, date, str]:
    """Rango y nombre de archivo para `exportar-dinero`: el mes pedido, el año pedido o el mes en curso."""
    if year:
        y = int(year)
        return date(y, 1, 1), date(y, 12, 31), f"dinero-{y}.csv"
    if month:
        y, m = (int(part) for part in month.split("-"))
    else:
        y, m = today.year, today.month
    start = date(y, m, 1)
    end = date(y + m // 12, m % 12 + 1, 1) - timedelta(days=1)
    return start, end, f"dinero-{y:04d}-{m:02d}.csv"
