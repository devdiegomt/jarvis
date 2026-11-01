"""Tools de dinero: gastos e ingresos, cuentas por cobrar y TRM.

Son datos internos de JARVIS que se pueden borrar, así que no piden confirmación (como los
pendientes). El modelo entiende el mensaje; las sumas y conversiones se calculan en código.
"""

import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from jarvis.money import Move, MoneyError, MoneyStore, Receivable, format_money, parse_amount
from jarvis.sensitive import has_long_number
from jarvis.tools.registry import Tool
from jarvis.trm import TrmError, TrmService, convert

MAX_TEXT_LENGTH = 200
MAX_LISTED = 50
CATEGORIES = (
    "comida, mercado, transporte, hogar, servicios, salud, trabajo, educación, ocio, ropa, regalos, otros"
)


def build_tools(
    store: MoneyStore, now: Callable[[], datetime], currency: str, trm: TrmService | None = None
) -> list[Tool]:
    """`currency`: moneda por defecto (JARVIS_MONEDA)."""

    def today() -> date:
        return now().date()

    def registrar_movimiento(
        tipo: str,
        monto: float,
        categoria: str,
        descripcion: str = "",
        fecha: str | None = None,
        moneda: str | None = None,
    ) -> str:
        day = _parse_date(fecha) if fecha else today()
        if day > today():
            raise MoneyError("No registro movimientos en el futuro: para algo por cobrar usa registrar_cobro.")
        move = store.add_move(
            tipo.strip().lower(),
            parse_amount(monto),
            _currency(moneda, currency),
            _clean(categoria, "la categoría").lower(),
            _clean(descripcion, "la descripción", required=False),
            day,
        )
        return _dump({"registrado": _move(move)})

    def listar_movimientos(
        desde: str | None = None, hasta: str | None = None, tipo: str | None = None, categoria: str | None = None
    ) -> str:
        end = _parse_date(hasta) if hasta else today()
        start = _parse_date(desde) if desde else end.replace(day=1)
        moves = store.moves_between(start, end)
        if tipo:
            moves = [m for m in moves if m.kind == tipo.strip().lower()]
        if categoria:
            moves = [m for m in moves if m.category == categoria.strip().lower()]
        totals: dict[str, Decimal] = {}
        for move in moves:
            key = f"{move.kind}s_{move.currency}"
            totals[key] = totals.get(key, Decimal(0)) + move.amount
        return _dump(
            {
                "desde": start.isoformat(),
                "hasta": end.isoformat(),
                "movimientos": [_move(m) for m in moves[:MAX_LISTED]],
                "total_movimientos": len(moves),
                "totales": {key: format_money(value, key.rsplit("_", 1)[1]) for key, value in totals.items()},
            }
        )

    def borrar_movimiento(id: int) -> str:  # noqa: A002 - nombre del parámetro visible para el modelo
        move = store.get_move(int(id))
        if move is None or not store.delete_move(move.id):
            raise MoneyError(f"No hay un movimiento con id {id}. Usa listar_movimientos.")
        return _dump({"borrado": _move(move)})

    def resumen_dinero(mes: str | None = None) -> str:
        year, month = _parse_month(mes) if mes else (today().year, today().month)
        summary = store.month_summary(year, month, currency)
        return _dump(
            {
                "mes": f"{year:04d}-{month:02d}",
                "moneda": currency,
                "gastos": format_money(summary.expenses, currency),
                "ingresos": format_money(summary.income, currency),
                "balance": format_money(summary.balance, currency),
                "gastos_por_categoria": {c: format_money(v, currency) for c, v in summary.by_category},
                "movimientos": summary.moves,
                "en_otras_monedas_sin_sumar": summary.other_currencies,
            }
        )

    def registrar_cobro(
        cliente: str, monto: float, vence: str | None = None, descripcion: str = "", moneda: str | None = None
    ) -> str:
        receivable = store.add_receivable(
            _clean(cliente, "el cliente"),
            parse_amount(monto),
            _currency(moneda, currency),
            _clean(descripcion, "la descripción", required=False),
            _parse_date(vence) if vence else None,
        )
        return _dump({"registrado": _receivable(receivable, today())})

    def listar_cobros(incluir_pagados: bool = False) -> str:
        current = today()
        pending = [_receivable(r, current) for r in store.open_receivables()]
        result: dict[str, Any] = {"hoy": current.isoformat(), "pendientes": pending}
        if incluir_pagados:
            since = current - timedelta(days=90)
            result["pagados_ultimos_90_dias"] = [_receivable(r, current) for r in store.paid_receivables(since)]
        return _dump(result)

    def marcar_cobro_pagado(id: int, registrar_ingreso: bool = True) -> str:  # noqa: A002
        receivable = store.get_receivable(int(id))
        if receivable is None or not store.mark_paid(receivable.id, today()):
            raise MoneyError(f"No hay un cobro pendiente con id {id}. Usa listar_cobros.")
        paid = store.get_receivable(receivable.id)
        assert paid is not None
        result: dict[str, Any] = {"pagado": _receivable(paid, today())}
        if registrar_ingreso:
            detail = f": {receivable.description}" if receivable.description else ""
            text = f"Pago de {receivable.client}{detail}"
            move = store.add_move("ingreso", receivable.amount, receivable.currency, "trabajo", text, today())
            result["ingreso_registrado"] = _move(move)
        return _dump(result)

    def borrar_cobro(id: int) -> str:  # noqa: A002
        receivable = store.get_receivable(int(id))
        if receivable is None or not store.delete_receivable(receivable.id):
            raise MoneyError(f"No hay un cobro con id {id}. Usa listar_cobros.")
        return _dump({"borrado": _receivable(receivable, today())})

    id_schema = _id_schema()
    tools = [
        Tool(
            name="registrar_movimiento",
            description=(
                "Registra un gasto o un ingreso del usuario (\"gasté 25 mil en almuerzo\", \"me pagaron 1,2 "
                "millones\"). El monto va como número (25 mil = 25000; 1,2 millones = 1200000). Elige una "
                f"categoría corta, de preferencia de esta lista: {CATEGORIES}. Si no queda claro si es "
                "gasto o ingreso, o el monto, pregunta antes. Avisa al usuario qué registraste."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": ["gasto", "ingreso"]},
                    "monto": {"type": "number", "description": "Monto positivo, sin puntos de miles."},
                    "categoria": {"type": "string", "description": "Categoría, por ejemplo «comida»."},
                    "descripcion": {"type": "string", "description": "Detalle breve (opcional)."},
                    "fecha": {"type": "string", "description": "YYYY-MM-DD; por defecto, hoy."},
                    "moneda": {"type": "string", "description": f"Código de 3 letras; por defecto {currency}."},
                },
                "required": ["tipo", "monto", "categoria"],
                "additionalProperties": False,
            },
            func=registrar_movimiento,
        ),
        Tool(
            name="listar_movimientos",
            description=(
                "Lista gastos e ingresos en un rango de fechas (por defecto, el mes en curso), con totales "
                "calculados. Úsala para responder cuánto gastó en algo o para encontrar el id a borrar."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "desde": {"type": "string", "description": "YYYY-MM-DD (por defecto, el día 1 del mes)."},
                    "hasta": {"type": "string", "description": "YYYY-MM-DD (por defecto, hoy)."},
                    "tipo": {"type": "string", "enum": ["gasto", "ingreso"]},
                    "categoria": {"type": "string"},
                },
                "additionalProperties": False,
            },
            func=listar_movimientos,
        ),
        Tool(
            name="borrar_movimiento",
            description="Borra un gasto o ingreso registrado por error, por su id (de listar_movimientos).",
            input_schema=id_schema,
            func=borrar_movimiento,
        ),
        Tool(
            name="resumen_dinero",
            description=(
                "Resumen de un mes: total de gastos, ingresos, balance y gastos por categoría, calculados "
                "en código. Usa estos totales tal cual; no sumes por tu cuenta."
            ),
            input_schema={
                "type": "object",
                "properties": {"mes": {"type": "string", "description": "YYYY-MM; por defecto, el mes en curso."}},
                "additionalProperties": False,
            },
            func=resumen_dinero,
        ),
        Tool(
            name="registrar_cobro",
            description=(
                "Registra algo que un cliente le debe al usuario (\"Acme me debe 3 millones, vence el 15\"). "
                "JARVIS le avisará el día que vence y, si sigue sin pagar, cada semana."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "cliente": {"type": "string"},
                    "monto": {"type": "number", "description": "Monto positivo, sin puntos de miles."},
                    "vence": {"type": "string", "description": "Fecha de vencimiento YYYY-MM-DD (opcional)."},
                    "descripcion": {"type": "string", "description": "Por ejemplo, el número de factura."},
                    "moneda": {"type": "string", "description": f"Código de 3 letras; por defecto {currency}."},
                },
                "required": ["cliente", "monto"],
                "additionalProperties": False,
            },
            func=registrar_cobro,
        ),
        Tool(
            name="listar_cobros",
            description="Lista lo que le deben al usuario (con días de atraso) y, si se pide, lo ya pagado.",
            input_schema={
                "type": "object",
                "properties": {"incluir_pagados": {"type": "boolean"}},
                "additionalProperties": False,
            },
            func=listar_cobros,
        ),
        Tool(
            name="marcar_cobro_pagado",
            description=(
                "Marca un cobro como pagado (\"Acme ya me pagó\"). Por defecto registra también el ingreso "
                "en la categoría «trabajo»; pon registrar_ingreso en false si el usuario ya lo registró."
            ),
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "integer"}, "registrar_ingreso": {"type": "boolean"}},
                "required": ["id"],
                "additionalProperties": False,
            },
            func=marcar_cobro_pagado,
        ),
        Tool(
            name="borrar_cobro",
            description="Borra un cobro registrado por error o que ya no aplica, por su id.",
            input_schema=id_schema,
            func=borrar_cobro,
        ),
    ]
    if trm is not None:
        tools.append(_trm_tool(trm, today))
    return tools


def _trm_tool(trm: TrmService, today: Callable[[], date]) -> Tool:
    def get_trm(monto: float | None = None, moneda: str = "USD", fecha: str | None = None) -> str:
        day = _parse_date(fecha) if fecha else today()
        try:
            rate = trm.on(day)
        except TrmError as exc:
            raise MoneyError(str(exc)) from exc
        result: dict[str, Any] = {
            "trm_cop_por_usd": str(rate.value),
            "texto": rate.line,
            "vigente_desde": rate.valid_from.isoformat(),
            "vigente_hasta": rate.valid_to.isoformat(),
            "fuente": "Superintendencia Financiera (datos.gov.co)",
        }
        if monto is not None:
            source = moneda.strip().upper()
            try:
                converted, target = convert(parse_amount(monto), source, rate)
            except TrmError as exc:
                raise MoneyError(str(exc)) from exc
            result["conversion"] = {
                "de": format_money(parse_amount(monto), source),
                "a": format_money(converted, target),
            }
        return _dump(result)

    return Tool(
        name="get_trm",
        description=(
            "TRM oficial del dólar en Colombia (hoy o en una fecha) y, si se da un monto, la conversión "
            "entre dólares y pesos calculada en código. Úsala en vez de buscar el dólar en internet."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "monto": {"type": "number", "description": "Monto a convertir (opcional)."},
                "moneda": {"type": "string", "enum": ["USD", "COP"], "description": "Moneda del monto."},
                "fecha": {"type": "string", "description": "YYYY-MM-DD; por defecto, hoy."},
            },
            "additionalProperties": False,
        },
        func=get_trm,
    )


def _move(move: Move) -> dict[str, Any]:
    return {
        "id": move.id,
        "tipo": move.kind,
        "monto": format_money(move.amount, move.currency),
        "categoria": move.category,
        "descripcion": move.description,
        "fecha": move.day.isoformat(),
    }


def _receivable(receivable: Receivable, today: date) -> dict[str, Any]:
    return {
        "id": receivable.id,
        "cliente": receivable.client,
        "monto": format_money(receivable.amount, receivable.currency),
        "descripcion": receivable.description,
        "vence": receivable.due_date.isoformat() if receivable.due_date else None,
        "dias_de_atraso": receivable.overdue_days(today),
        "pagado_el": receivable.paid_on.isoformat() if receivable.paid_on else None,
    }


def _clean(value: str, what: str, required: bool = True) -> str:
    text = " ".join((value or "").split())
    if required and not text:
        raise MoneyError(f"Falta {what}.")
    if len(text) > MAX_TEXT_LENGTH:
        raise MoneyError(f"{what.capitalize()} no puede superar {MAX_TEXT_LENGTH} caracteres.")
    if has_long_number(text):
        raise MoneyError(
            "No guardo números largos (tarjetas, cuentas, documentos). Dile al usuario que por seguridad "
            "no lo anotarás, y registra el movimiento sin ese número."
        )
    return text


def _currency(value: str | None, default: str) -> str:
    code = (value or default).strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise MoneyError(f"«{value}» no es un código de moneda: usa 3 letras, por ejemplo COP o USD.")
    return code


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise MoneyError(f"Fecha inválida «{value}»: usa el formato YYYY-MM-DD.") from None


def _parse_month(value: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in value.strip().split("-"))
        date(year, month, 1)
    except ValueError:
        raise MoneyError(f"Mes inválido «{value}»: usa el formato YYYY-MM.") from None
    return year, month


def _id_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
        "additionalProperties": False,
    }


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)
