import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest

from jarvis.agenda import SampleCalendar
from jarvis.config import ConfigError, ProactiveSettings, load_money_settings, load_settings
from jarvis.money import MoneyError, MoneyStore, format_money, parse_amount
from jarvis.money_report import (
    export_period,
    month_text,
    moves_csv,
    receivable_alert,
    receivables_text,
    trm_text,
)
from jarvis.proactive import NoticeLog, ProactiveNotifier
from jarvis.prompts import build_chat_system_prompt
from jarvis.quick import build_quick_commands, today_data, today_text
from jarvis.reminders import ReminderStore
from jarvis.summary import build_summary
from jarvis.tasks import TaskStore
from jarvis.tools import build_registry
from jarvis.trm import TrmError, TrmService
from jarvis.usage import UsageLog

TZ = ZoneInfo("America/Bogota")
NOW = datetime(2026, 11, 16, 10, 0, tzinfo=TZ)  # lunes
TODAY = NOW.date()
TRM_ROW = [{"valor": "4123.45", "vigenciadesde": "2026-11-14T00:00:00.000", "vigenciahasta": "2026-11-17T00:00:00.000"}]


def store(tmp_path: Path, now: datetime = NOW) -> MoneyStore:
    return MoneyStore(tmp_path / "jarvis.db", now=lambda: now)


class FakeDatos:
    def __init__(self, rows: Any = TRM_ROW) -> None:
        self.rows = rows
        self.urls: list[str] = []

    def __call__(self, url: str, _timeout: float) -> Any:
        self.urls.append(url)
        return self.rows


# --- Montos y almacén -----------------------------------------------------------


def test_amounts_and_formatting() -> None:
    assert parse_amount(25000) == Decimal("25000")
    assert parse_amount(0.1) + parse_amount(0.2) == Decimal("0.3")  # sin errores de coma flotante
    for bad in (0, -5, "veinte", float("nan"), 10**13):
        with pytest.raises(MoneyError):
            parse_amount(bad)
    assert format_money(Decimal("1200000"), "COP") == "$1.200.000"
    assert format_money(Decimal("25000.6"), "COP") == "$25.001"
    assert format_money(Decimal("1234.5"), "USD") == "$1.234,50 USD"


def test_moves_and_month_summary(tmp_path: Path) -> None:
    money = store(tmp_path)
    money.add_move("gasto", Decimal("25000"), "COP", "comida", "Almuerzo", TODAY)
    money.add_move("gasto", Decimal("80000"), "COP", "transporte", "Gasolina", TODAY - timedelta(days=3))
    money.add_move("gasto", Decimal("15000"), "COP", "comida", "", TODAY)
    money.add_move("ingreso", Decimal("1200000"), "COP", "trabajo", "Acme", TODAY)
    money.add_move("gasto", Decimal("20"), "USD", "ocio", "Suscripción", TODAY)
    money.add_move("gasto", Decimal("99999"), "COP", "comida", "Mes pasado", date(2026, 10, 31))

    summary = money.month_summary(2026, 11, "COP")

    assert (summary.expenses, summary.income, summary.balance) == (Decimal(120000), Decimal(1200000), Decimal(1080000))
    assert summary.by_category == [("transporte", Decimal(80000)), ("comida", Decimal(40000))]
    assert summary.other_currencies == 1
    with pytest.raises(MoneyError):
        money.add_move("prestamo", Decimal(1), "COP", "x", "", TODAY)


def test_receivables(tmp_path: Path) -> None:
    money = store(tmp_path)
    later = money.add_receivable("Globex", Decimal("500"), "USD", "", None)
    late = money.add_receivable("Acme", Decimal("3000000"), "COP", "Factura 12", TODAY - timedelta(days=3))

    assert [r.client for r in money.open_receivables()] == ["Acme", "Globex"]
    assert late.overdue_days(TODAY) == 3 and later.overdue_days(TODAY) == 0
    assert money.mark_paid(late.id, TODAY) and not money.mark_paid(late.id, TODAY)
    assert [r.client for r in money.open_receivables()] == ["Globex"]
    assert money.paid_receivables(TODAY - timedelta(days=1))[0].paid_on == TODAY


# --- Tools ------------------------------------------------------------------------


def registry(tmp_path: Path, trm: TrmService | None = None) -> Any:
    return build_registry(SampleCalendar(TZ), now=lambda: NOW, money=store(tmp_path), currency="COP", trm=trm)


def call(reg: Any, name: str, args: dict[str, Any]) -> Any:
    result = reg.execute(name, args)
    assert not result.is_error, result.content
    return json.loads(result.content)


def test_expenses_by_chat(tmp_path: Path) -> None:
    reg = registry(tmp_path)

    added = call(reg, "registrar_movimiento", {"tipo": "gasto", "monto": 25000, "categoria": "Comida", "descripcion": "Almuerzo"})
    call(reg, "registrar_movimiento", {"tipo": "ingreso", "monto": 1200000, "categoria": "trabajo", "fecha": "2026-11-02"})
    listed = call(reg, "listar_movimientos", {"tipo": "gasto"})
    summary = call(reg, "resumen_dinero", {})

    assert added["registrado"] == {
        "id": 1, "tipo": "gasto", "monto": "$25.000", "categoria": "comida", "descripcion": "Almuerzo", "fecha": "2026-11-16",
    }
    assert listed["total_movimientos"] == 1 and listed["totales"] == {"gastos_COP": "$25.000"}
    assert summary["balance"] == "$1.175.000" and summary["gastos_por_categoria"] == {"comida": "$25.000"}
    assert call(reg, "borrar_movimiento", {"id": 1})["borrado"]["monto"] == "$25.000"
    for name in ("registrar_movimiento", "registrar_cobro", "marcar_cobro_pagado", "borrar_movimiento"):
        assert not reg.get(name).requires_confirmation  # datos internos que se pueden deshacer


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"tipo": "gasto", "monto": 10, "categoria": "x", "fecha": "2026-11-20"}, "futuro"),
        ({"tipo": "gasto", "monto": 10, "categoria": "x", "descripcion": "tarjeta 4111 1111 1111 1111"}, "números largos"),
        ({"tipo": "gasto", "monto": -10, "categoria": "x"}, "mayor que cero"),
        ({"tipo": "gasto", "monto": 10, "categoria": "x", "moneda": "pesos"}, "3 letras"),
        ({"tipo": "gasto", "monto": 10, "categoria": " "}, "Falta la categoría"),
    ],
)
def test_invalid_moves_are_explained(tmp_path: Path, args: dict[str, Any], expected: str) -> None:
    result = registry(tmp_path).execute("registrar_movimiento", args)

    assert result.is_error and expected in result.content


def test_receivables_by_chat(tmp_path: Path) -> None:
    reg = registry(tmp_path)

    call(reg, "registrar_cobro", {"cliente": "Acme", "monto": 3000000, "vence": "2026-11-13", "descripcion": "Factura 12"})
    pending = call(reg, "listar_cobros", {})["pendientes"]
    paid = call(reg, "marcar_cobro_pagado", {"id": pending[0]["id"]})
    summary = call(reg, "resumen_dinero", {})

    assert pending[0]["dias_de_atraso"] == 3
    assert paid["pagado"]["pagado_el"] == "2026-11-16"
    assert paid["ingreso_registrado"]["descripcion"] == "Pago de Acme: Factura 12"
    assert summary["ingresos"] == "$3.000.000"
    assert call(reg, "listar_cobros", {"incluir_pagados": True})["pagados_ultimos_90_dias"][0]["cliente"] == "Acme"
    assert reg.execute("marcar_cobro_pagado", {"id": 1}).is_error  # ya estaba pagado


def test_trm_tool_converts_in_code(tmp_path: Path) -> None:
    reg = registry(tmp_path, TrmService(fetch=FakeDatos()))

    usd = call(reg, "get_trm", {"monto": 500, "moneda": "USD"})
    cop = call(reg, "get_trm", {"monto": 1000000, "moneda": "COP"})

    assert usd["trm_cop_por_usd"] == "4123.45" and usd["conversion"] == {"de": "$500,00 USD", "a": "$2.061.725"}
    assert cop["conversion"]["a"] == "$242,52 USD"
    assert "get_trm" not in registry(tmp_path).names()


# --- TRM --------------------------------------------------------------------------


def test_trm_query_and_cache() -> None:
    datos = FakeDatos()
    trm = TrmService(fetch=datos)

    rate = trm.on(TODAY)
    trm.on(TODAY)

    assert rate.value == Decimal("4123.45") and rate.valid_from == date(2026, 11, 14)
    assert rate.line == "TRM: $4.123,45 por dólar"
    assert len(datos.urls) == 1
    where = parse_qs(urlsplit(datos.urls[0]).query)["$where"][0]
    assert "vigenciadesde <= '2026-11-16T00:00:00.000'" in where


def test_trm_errors() -> None:
    with pytest.raises(TrmError, match="Todavía no hay TRM"):
        TrmService(fetch=FakeDatos([])).on(TODAY)
    with pytest.raises(TrmError, match="no entiendo"):
        TrmService(fetch=FakeDatos([{"valor": "x"}])).on(TODAY)
    # Sin red (en los tests nunca hay): el resumen y /hoy simplemente omiten la línea.
    assert TrmService().line(TODAY) is None
    assert "sin red" in trm_text(TrmService(), TODAY)


# --- Textos y avisos (sin IA) --------------------------------------------------


def test_month_text_compares_with_last_month(tmp_path: Path) -> None:
    money = store(tmp_path)
    assert "todavía no has registrado" in month_text(money, TODAY, "COP")
    money.add_move("gasto", Decimal("100000"), "COP", "comida", "", date(2026, 10, 10))
    money.add_move("gasto", Decimal("80000"), "COP", "comida", "", TODAY)
    money.add_move("gasto", Decimal("40000"), "COP", "hogar", "", TODAY)
    money.add_move("ingreso", Decimal("50000"), "COP", "trabajo", "", TODAY)

    assert month_text(money, TODAY, "COP") == (
        "💰 Noviembre 2026\nGastos: $120.000\n- comida: $80.000\n- hogar: $40.000\nIngresos: $50.000\n"
        "Balance: -$70.000\nLlevas 20% más de gastos que en todo octubre ($100.000)."
    )


def test_receivables_text_and_alerts(tmp_path: Path) -> None:
    money = store(tmp_path)
    assert "Nadie te debe nada" in receivables_text(money, TODAY)
    money.add_receivable("Globex", Decimal("500"), "USD", "", TODAY + timedelta(days=5))
    late = money.add_receivable("Acme", Decimal("3000000"), "COP", "Factura 12", TODAY - timedelta(days=14))
    due = money.add_receivable("Initech", Decimal("700000"), "COP", "", TODAY)

    assert receivables_text(money, TODAY) == (
        "🧾 Te deben $3.700.000 + $500,00 USD:\n- Acme: $3.000.000 (Factura 12) · vencido hace 14 días\n"
        "- Initech: $700.000 · vence hoy\n- Globex: $500,00 USD · vence el 21/11"
    )
    assert receivable_alert(due, TODAY) == "💰 Hoy vence el cobro a Initech: $700.000."
    assert receivable_alert(late, TODAY) == "⚠️ Acme sigue sin pagarte $3.000.000 (Factura 12): venció hace 2 semanas."


class Channel:
    name = "prueba"

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_text(self, to: str, text: str) -> None:
        self.sent.append(text)


def notifier(tmp_path: Path, clock: list[datetime], channel: Channel) -> ProactiveNotifier:
    db = tmp_path / "jarvis.db"
    return ProactiveNotifier(
        calendar=SampleCalendar(TZ),
        tasks=TaskStore(db, now=lambda: clock[0]),
        channel=channel,
        owner="1",
        settings=ProactiveSettings(0, None),
        log=NoticeLog(db),
        timezone=TZ,
        now=lambda: clock[0],
        money=MoneyStore(db, now=lambda: clock[0]),
        receivable_time=time(9, 0),
    )


def test_receivable_reminders_on_due_day_and_weekly(tmp_path: Path) -> None:
    money = store(tmp_path)
    money.add_receivable("Acme", Decimal("3000000"), "COP", "", date(2026, 11, 2))  # vence un lunes
    clock, channel = [datetime(2026, 11, 2, 8, 59, tzinfo=TZ)], Channel()
    proactive = notifier(tmp_path, clock, channel)

    proactive.check()  # antes de las 9: nada
    clock[0] = datetime(2026, 11, 2, 9, 0, tzinfo=TZ)
    proactive.check()
    proactive.check()  # una sola vez por día
    for day in (3, 8, 9, 16):
        clock[0] = datetime(2026, 11, day, 12, 0, tzinfo=TZ)
        proactive.check()

    assert channel.sent == [
        "💰 Hoy vence el cobro a Acme: $3.000.000.",
        "⚠️ Acme sigue sin pagarte $3.000.000: venció hace 1 semana.",  # el 9
        "⚠️ Acme sigue sin pagarte $3.000.000: venció hace 2 semanas.",  # el 16
    ]


def test_paid_receivables_are_not_reminded(tmp_path: Path) -> None:
    money = store(tmp_path)
    receivable = money.add_receivable("Acme", Decimal("1"), "COP", "", TODAY)
    money.mark_paid(receivable.id, TODAY)
    channel = Channel()

    notifier(tmp_path, [NOW], channel).check()

    assert channel.sent == []


def test_today_views_and_commands_include_money(tmp_path: Path) -> None:
    db = tmp_path / "jarvis.db"
    money = store(tmp_path)
    money.add_receivable("Acme", Decimal("3000000"), "COP", "", TODAY - timedelta(days=1))
    tasks, reminders = TaskStore(db, now=lambda: NOW), ReminderStore(db, now=lambda: NOW)
    views = {"calendar": SampleCalendar(TZ), "tasks": tasks, "reminders": reminders, "weather": None, "now": NOW, "timezone": TZ}

    assert "Cobros (vencen hoy o vencidos):\n- Acme: $3.000.000 · vencido hace 1 día" in today_text(**views, money=money)
    assert today_data(**views, money=money)["cobros"] == [
        {"cliente": "Acme", "monto": "$3.000.000", "vence": "2026-11-15", "dias_de_atraso": 1}
    ]
    commands = build_quick_commands(
        calendar=SampleCalendar(TZ), tasks=tasks, reminders=reminders, weather=None,
        usage=UsageLog(db, now=lambda: NOW), now=lambda: NOW, timezone=TZ, money=money, trm=TrmService(fetch=FakeDatos()),
    )
    assert commands["/cobros"]().startswith("🧾 Te deben $3.000.000")
    assert commands["/dinero"]().startswith("💰 Noviembre 2026")
    assert commands["/trm"]().startswith("💵 TRM: $4.123,45 por dólar")


def test_summary_extras_and_prompt() -> None:
    body = build_summary(TODAY, [], None, "ejemplo", extras=["TRM: $4.123,45 por dólar", "Cobros: Acme: $1"]).body

    assert "\n\nTRM: $4.123,45 por dólar\nCobros: Acme: $1\n\n" in body
    assert "registrar_movimiento" in build_chat_system_prompt(TODAY)
    assert "no \nsumes" not in build_chat_system_prompt(TODAY) and "no sumes" in build_chat_system_prompt(TODAY)


# --- Exportar, configuración y estado --------------------------------------------


def test_csv_export(tmp_path: Path) -> None:
    money = store(tmp_path)
    money.add_move("gasto", Decimal("25000"), "COP", "comida", "Almuerzo, con postre", TODAY)
    money.add_move("ingreso", Decimal("1200000"), "COP", "trabajo", "Acme", date(2026, 11, 2))

    assert moves_csv(money, date(2026, 11, 1), date(2026, 11, 30)).splitlines() == [
        "fecha,tipo,categoria,descripcion,monto,moneda",
        "2026-11-02,ingreso,trabajo,Acme,1200000.00,COP",
        '2026-11-16,gasto,comida,"Almuerzo, con postre",25000.00,COP',
    ]
    assert export_period(TODAY, None, None) == (date(2026, 11, 1), date(2026, 11, 30), "dinero-2026-11.csv")
    assert export_period(TODAY, "2026-12", None)[1] == date(2026, 12, 31)
    assert export_period(TODAY, None, "2025") == (date(2025, 1, 1), date(2025, 12, 31), "dinero-2025.csv")


def test_export_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from jarvis import cli

    settings = load_settings({"ANTHROPIC_API_KEY": "k", "JARVIS_DB_PATH": str(tmp_path / "jarvis.db")})
    MoneyStore(settings.summary.db_path, now=lambda: NOW).add_move(
        "gasto", Decimal("25000"), "COP", "comida", "", datetime.now(settings.timezone).date()
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)

    cli.run_export_money(None, None, str(tmp_path / "mes.csv"))

    assert (tmp_path / "mes.csv").read_text(encoding="utf-8-sig").count("\n") == 2
    assert "1 movimiento(s)" in capsys.readouterr().out


def test_settings_and_status(isolated_config_dir: Path) -> None:
    from jarvis.status import status_report

    assert load_money_settings({"JARVIS_MONEDA": "usd", "JARVIS_AVISO_COBROS": "no"}).currency == "USD"
    with pytest.raises(ConfigError, match="JARVIS_MONEDA"):
        load_money_settings({"JARVIS_MONEDA": "pesos"})

    env = {"ANTHROPIC_API_KEY": "k"}
    assert "Dinero: sin movimientos ni cobros" in status_report(env, None, {})
    db = isolated_config_dir / "jarvis.db"
    MoneyStore(db, now=lambda: NOW).add_receivable("Acme", Decimal(1), "COP", "", date(2020, 1, 1))
    line = next(l for l in status_report(env, None, {}) if l.startswith("Dinero:"))
    assert line == "Dinero: 0 movimiento(s) este mes, 1 cobro(s) pendiente(s) (1 vencido(s)), aviso de cobros a las 09:00"
