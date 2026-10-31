import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest

from jarvis.agenda import SampleCalendar
from jarvis.chat import COMMANDS, HELP_TEXT
from jarvis.proactive import evening_preview
from jarvis.prompts import build_chat_system_prompt
from jarvis.quick import NO_CITY_TEXT, build_quick_commands, reminders_text, tasks_text, today_text
from jarvis.reminders import ReminderStore
from jarvis.summary import build_summary
from jarvis.tasks import TaskStore
from jarvis.tools import build_registry
from jarvis.usage import UsageLog
from jarvis.weather import WeatherError, WeatherService, day_line, weather_text

TZ = ZoneInfo("America/Bogota")
NOW = datetime(2026, 11, 2, 7, 30, tzinfo=TZ)  # lunes
TODAY = NOW.date()

PLACE = {"results": [{"name": "Zipaquirá", "admin1": "Cundinamarca", "country": "Colombia", "latitude": 5.02, "longitude": -74.0}]}
FORECAST = {
    "current": {"time": "2026-11-02T07:30", "temperature_2m": 11.4, "weather_code": 3},
    "daily": {
        "time": ["2026-11-02", "2026-11-03", "2026-11-04"],
        "weather_code": [61, 2, 95],
        "temperature_2m_min": [8.6, 7.9, 9.1],
        "temperature_2m_max": [17.2, 19.0, 16.4],
        "precipitation_probability_max": [80, 10, 95],
        "precipitation_sum": [4.2, 0.0, 12.5],
        "wind_speed_10m_max": [14.0, 9.5, 22.3],
    },
}


class OpenMeteo:
    """Sustituye las llamadas HTTP: responde según la URL y registra cada consulta."""

    def __init__(self, place: Any = PLACE, forecast: Any = FORECAST, error: Exception | None = None) -> None:
        self.place, self.forecast, self.error = place, forecast, error
        self.urls: list[str] = []

    def __call__(self, url: str, _timeout: float) -> Any:
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.place if "geocoding" in url else self.forecast


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def service(api: OpenMeteo | None = None, clock: Clock | None = None) -> WeatherService:
    return WeatherService("Zipaquirá", "CO", TZ, fetch=api or OpenMeteo(), clock=clock or Clock())


# --- Open-Meteo -------------------------------------------------------------


def test_report_locates_the_city_and_reads_the_forecast() -> None:
    api = OpenMeteo()

    report = service(api).report()

    assert report.place.label == "Zipaquirá (Cundinamarca)"
    assert report.current is not None and report.current.temperature == 11.4
    assert [d.day for d in report.days] == [date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)]
    geo, forecast = (parse_qs(urlsplit(url).query) for url in api.urls)
    assert geo["name"] == ["Zipaquirá"] and geo["countryCode"] == ["CO"]
    assert forecast["timezone"] == ["America/Bogota"] and forecast["latitude"] == ["5.02"]


def test_forecast_is_cached_for_half_an_hour() -> None:
    api, clock = OpenMeteo(), Clock()
    weather = service(api, clock)

    weather.report()
    clock.now += 29 * 60
    weather.report()
    clock.now += 2 * 60
    weather.report()

    assert len(api.urls) == 3  # ubicar una vez, y el pronóstico dos veces


def test_unknown_city_and_network_errors() -> None:
    with pytest.raises(WeatherError, match="JARVIS_CIUDAD"):
        service(OpenMeteo(place={"results": []})).report()
    with pytest.raises(WeatherError, match="no entiendo"):
        service(OpenMeteo(forecast={"daily": {}})).report()

    offline = service(OpenMeteo(error=WeatherError("sin red")))
    assert offline.day(TODAY) is None  # para los avisos: sin clima, sin línea


def test_texts() -> None:
    report = service().report()

    assert day_line(report.days[0]) == "🌧 lluvia débil, 9–17 °C, 80 % de probabilidad de lluvia (4,2 mm)"
    assert day_line(report.days[1]) == "⛅ parcialmente nublado, 8–19 °C"  # 10 %: no se menciona
    assert weather_text(report, TODAY) == (
        "Clima en Zipaquirá (Cundinamarca)\nAhora: ☁️ 11 °C, nublado\n"
        "- Hoy: 🌧 lluvia débil, 9–17 °C, 80 % de probabilidad de lluvia (4,2 mm)\n"
        "- Mañana: ⛅ parcialmente nublado, 8–19 °C\n"
        "- Miércoles 4 de noviembre: ⛈ tormenta, 9–16 °C, 95 % de probabilidad de lluvia (12,5 mm)\n"
        "Fuente: Open-Meteo"
    )


# --- Tool y prompt ----------------------------------------------------------


def test_weather_tool() -> None:
    registry = build_registry(SampleCalendar(TZ), now=lambda: NOW, weather=service())

    result = json.loads(registry.execute("get_clima", {"dias": 2}).content)

    assert result["lugar"] == "Zipaquirá (Cundinamarca)" and result["ahora"]["temperatura_c"] == 11
    assert [d["fecha"] for d in result["dias"]] == ["2026-11-02", "2026-11-03"]
    assert result["dias"][0]["prob_lluvia_pct"] == 80 and result["dias"][0]["descripcion"] == "lluvia débil"
    assert not registry.get("get_clima").requires_confirmation  # type: ignore[union-attr]
    assert registry.execute("get_clima", {"dias": 9}).is_error
    assert "get_clima" not in build_registry(SampleCalendar(TZ), now=lambda: NOW).names()


def test_weather_tool_errors_suggest_searching() -> None:
    registry = build_registry(SampleCalendar(TZ), now=lambda: NOW, weather=service(OpenMeteo(error=WeatherError("sin red"))))

    result = registry.execute("get_clima", {})

    assert result.is_error and "buscarlo en internet" in result.content


def test_prompt_prefers_the_free_weather_tool() -> None:
    assert "get_clima" in build_chat_system_prompt(TODAY, weather=True)
    assert "get_clima" not in build_chat_system_prompt(TODAY)


# --- Comandos directos --------------------------------------------------------


def stores(tmp_path: Path) -> tuple[TaskStore, ReminderStore]:
    db = tmp_path / "jarvis.db"
    return TaskStore(db, now=lambda: NOW), ReminderStore(db, now=lambda: NOW)


def test_today_brings_everything_together(tmp_path: Path) -> None:
    tasks, reminders = stores(tmp_path)
    tasks.add("Renovar el pasaporte", date(2026, 10, 30))
    tasks.add("Comprar regalo", date(2026, 11, 20))
    reminders.create("Llamar a Laura", NOW.replace(hour=17, minute=0))
    reminders.create("Pagar el arriendo", NOW + timedelta(days=1))

    text = today_text(calendar=SampleCalendar(TZ), tasks=tasks, reminders=reminders, weather=service(), now=NOW, timezone=TZ)

    assert text.startswith("📅 Hoy, lunes 2 de noviembre\n🌧 lluvia débil, 9–17 °C")
    assert "\nReuniones:\n- 09:30-10:00  Daily del equipo" in text
    assert "\nRecordatorios:\n- 17:00  Llamar a Laura" in text and "arriendo" not in text
    assert "Pendientes (vencen hoy o atrasados):\n- Renovar el pasaporte (atrasado: era para el 30/10)" in text
    assert "regalo" not in text


def test_today_without_weather_or_calendar(tmp_path: Path) -> None:
    from jarvis.agenda import CalendarError

    tasks, reminders = stores(tmp_path)
    broken = type("C", (), {"name": "x", "list_meetings": lambda *_: (_ for _ in ()).throw(CalendarError("sin red"))})()

    text = today_text(calendar=broken, tasks=tasks, reminders=reminders, weather=None, now=NOW, timezone=TZ)  # type: ignore[arg-type]

    assert text == "📅 Hoy, lunes 2 de noviembre\n\nNo pude leer el calendario: sin red"


def test_tasks_and_reminders_lists(tmp_path: Path) -> None:
    tasks, reminders = stores(tmp_path)
    assert "No tienes pendientes" in tasks_text(tasks, TODAY)
    assert "No tienes recordatorios" in reminders_text(reminders, NOW, TZ)

    tasks.add("Llamar al banco")
    tasks.add("Enviar la propuesta", date(2026, 11, 3))
    reminders.create("Tomar la pastilla", NOW.replace(hour=21, minute=0))
    reminders.create("Cita médica", datetime(2026, 11, 5, 8, 0, tzinfo=TZ))

    assert tasks_text(tasks, TODAY) == "📝 Pendientes (2):\n- Enviar la propuesta (para mañana)\n- Llamar al banco"
    assert reminders_text(reminders, NOW, TZ) == (
        "⏰ Recordatorios (2):\n- hoy, 21:00: Tomar la pastilla\n- el jueves 5 de noviembre, 08:00: Cita médica"
    )


def test_quick_commands_are_in_the_menu_and_help(tmp_path: Path) -> None:
    tasks, reminders = stores(tmp_path)
    commands = build_quick_commands(
        calendar=SampleCalendar(TZ),
        tasks=tasks,
        reminders=reminders,
        weather=None,
        usage=UsageLog(tmp_path / "jarvis.db", now=lambda: NOW),
        now=lambda: NOW,
        timezone=TZ,
    )

    assert set(commands) == {"/hoy", "/pendientes", "/recordatorios", "/clima", "/gasto"}
    assert all(name.removeprefix("/") in COMMANDS and name in HELP_TEXT for name in commands)
    assert commands["/clima"]() == NO_CITY_TEXT
    assert commands["/gasto"]().startswith("💸 Gasto estimado en Claude")


# --- Resumen y vistazo a mañana -----------------------------------------------


def test_summary_and_evening_preview_include_the_weather() -> None:
    line = day_line(service().report().days[0])

    summary = build_summary(TODAY, [], None, "ejemplo", weather=line)
    assert "\n\nClima: 🌧 lluvia débil, 9–17 °C" in summary.body
    assert "Clima:" not in build_summary(TODAY, [], None, "ejemplo").body

    assert evening_preview(TODAY, [], [], line) == (
        "🌙 Mañana, lunes 2 de noviembre: no tienes reuniones.\n🌧 lluvia débil, 9–17 °C, 80 % de probabilidad de lluvia (4,2 mm)"
    )


def test_status_shows_the_weather_city(isolated_config_dir: Path) -> None:
    from jarvis.status import status_report

    env = {"ANTHROPIC_API_KEY": "sk-test"}
    assert "Clima: sin ciudad (configura JARVIS_CIUDAD)" in status_report(env, None, {})
    assert "Clima: Open-Meteo para Zipaquirá, CO" in status_report({**env, "JARVIS_CIUDAD": "Zipaquirá", "JARVIS_PAIS": "CO"}, None, {})
