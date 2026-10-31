"""Clima con Open-Meteo (https://open-meteo.com): gratis, sin clave y sin gastar créditos de IA.

Sirve a la tool `get_clima`, al comando `/clima`, a `/hoy`, al resumen de la mañana y al vistazo a
mañana. La ubicación sale de `JARVIS_CIUDAD` y `JARVIS_PAIS`; solo se envían a Open-Meteo el nombre
de la ciudad (para ubicarla) y sus coordenadas, nunca nada del usuario.
"""

import json
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, tzinfo
from functools import cache
from typing import Any

import truststore

from jarvis.dates import format_spanish_date

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FORECAST_DAYS = 7
CACHE_SECONDS = 30 * 60  # el pronóstico cambia poco: se consulta como mucho cada media hora
TIMEOUT_SECONDS = 10
RAIN_WORTH_MENTIONING = 20  # % de probabilidad desde el que se nombra la lluvia en una línea

# Códigos WMO que usa Open-Meteo: (descripción, emoji).
_WEATHER_CODES = {
    0: ("despejado", "☀️"),
    1: ("mayormente despejado", "🌤"),
    2: ("parcialmente nublado", "⛅"),
    3: ("nublado", "☁️"),
    45: ("niebla", "🌫"),
    48: ("niebla con escarcha", "🌫"),
    51: ("llovizna débil", "🌦"),
    53: ("llovizna", "🌦"),
    55: ("llovizna intensa", "🌦"),
    56: ("llovizna helada", "🌧"),
    57: ("llovizna helada intensa", "🌧"),
    61: ("lluvia débil", "🌧"),
    63: ("lluvia", "🌧"),
    65: ("lluvia fuerte", "🌧"),
    66: ("lluvia helada", "🌧"),
    67: ("lluvia helada fuerte", "🌧"),
    71: ("nieve débil", "🌨"),
    73: ("nieve", "🌨"),
    75: ("nieve fuerte", "🌨"),
    77: ("granizo fino", "🌨"),
    80: ("chubascos débiles", "🌦"),
    81: ("chubascos", "🌦"),
    82: ("chubascos fuertes", "⛈"),
    85: ("chubascos de nieve", "🌨"),
    86: ("chubascos de nieve fuertes", "🌨"),
    95: ("tormenta", "⛈"),
    96: ("tormenta con granizo", "⛈"),
    99: ("tormenta con granizo fuerte", "⛈"),
}

# Hace un GET y devuelve el JSON (reemplazable en los tests).
FetchJson = Callable[[str, float], Any]


class WeatherError(Exception):
    """No se pudo consultar el clima. El mensaje está pensado para el usuario."""


@dataclass(frozen=True)
class Place:
    name: str
    region: str
    country: str
    latitude: float
    longitude: float

    @property
    def label(self) -> str:
        return f"{self.name} ({self.region})" if self.region and self.region != self.name else self.name


@dataclass(frozen=True)
class DayForecast:
    day: date
    code: int
    temp_min: float
    temp_max: float
    rain_chance: int | None  # % máximo del día
    rain_mm: float | None
    wind_max: float | None  # km/h

    @property
    def description(self) -> str:
        return describe_code(self.code)[0]

    @property
    def emoji(self) -> str:
        return describe_code(self.code)[1]


@dataclass(frozen=True)
class CurrentWeather:
    temperature: float
    code: int


@dataclass(frozen=True)
class WeatherReport:
    place: Place
    current: CurrentWeather | None
    days: list[DayForecast]

    def day(self, day: date) -> DayForecast | None:
        return next((forecast for forecast in self.days if forecast.day == day), None)


def describe_code(code: int) -> tuple[str, str]:
    return _WEATHER_CODES.get(code, ("condición desconocida", "🌡"))


class WeatherService:
    """Pronóstico de la ciudad configurada, con caché en memoria (es compartido entre hilos)."""

    def __init__(
        self,
        city: str,
        country: str,
        timezone: tzinfo,
        fetch: FetchJson | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._city = city
        self._country = country
        self._timezone_name = getattr(timezone, "key", None) or "auto"
        self._fetch = fetch or http_get_json
        self._clock = clock
        self._lock = threading.Lock()
        self._place: Place | None = None
        self._report: WeatherReport | None = None
        self._fetched_at = 0.0

    def report(self) -> WeatherReport:
        """Clima actual y de los próximos 7 días. Lanza WeatherError si no se pudo consultar."""
        with self._lock:
            if self._report is None or self._clock() - self._fetched_at >= CACHE_SECONDS:
                place = self._place or self._locate()
                self._place = place
                self._report = self._forecast(place)
                self._fetched_at = self._clock()
            return self._report

    def day(self, day: date) -> DayForecast | None:
        """Pronóstico de un día, o None si no está disponible (sin red, fuera de rango…)."""
        try:
            return self.report().day(day)
        except WeatherError:
            return None

    def _locate(self) -> Place:
        params = {"name": self._city, "count": 1, "language": "es", "format": "json"}
        if self._country:
            params["countryCode"] = self._country
        data = self._fetch(f"{GEOCODING_URL}?{urllib.parse.urlencode(params)}", TIMEOUT_SECONDS)
        results = data.get("results") if isinstance(data, dict) else None
        if not results:
            raise WeatherError(f"No encontré la ciudad «{self._city}» en Open-Meteo: revisa JARVIS_CIUDAD.")
        first = results[0]
        try:
            return Place(
                name=str(first["name"]),
                region=str(first.get("admin1") or ""),
                country=str(first.get("country") or ""),
                latitude=float(first["latitude"]),
                longitude=float(first["longitude"]),
            )
        except (KeyError, TypeError, ValueError):
            raise WeatherError("Open-Meteo devolvió una ubicación que no entiendo.") from None

    def _forecast(self, place: Place) -> WeatherReport:
        params = {
            "latitude": place.latitude,
            "longitude": place.longitude,
            "current": "temperature_2m,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
            "precipitation_sum,wind_speed_10m_max",
            "timezone": self._timezone_name,
            "forecast_days": FORECAST_DAYS,
        }
        data = self._fetch(f"{FORECAST_URL}?{urllib.parse.urlencode(params)}", TIMEOUT_SECONDS)
        try:
            return WeatherReport(place, _parse_current(data.get("current")), _parse_days(data["daily"]))
        except (AttributeError, KeyError, TypeError, ValueError, IndexError):
            raise WeatherError("Open-Meteo devolvió un pronóstico que no entiendo.") from None


def _parse_current(current: Any) -> CurrentWeather | None:
    if not isinstance(current, dict) or current.get("temperature_2m") is None:
        return None
    return CurrentWeather(float(current["temperature_2m"]), int(current.get("weather_code") or 0))


def _parse_days(daily: dict[str, list[Any]]) -> list[DayForecast]:
    def optional(name: str, index: int) -> Any:
        values = daily.get(name) or []
        return values[index] if index < len(values) else None

    days = []
    for index, day in enumerate(daily["time"]):
        chance, rain, wind = (optional(name, index) for name in (
            "precipitation_probability_max", "precipitation_sum", "wind_speed_10m_max"
        ))
        days.append(
            DayForecast(
                day=date.fromisoformat(day),
                code=int(daily["weather_code"][index] or 0),
                temp_min=float(daily["temperature_2m_min"][index]),
                temp_max=float(daily["temperature_2m_max"][index]),
                rain_chance=int(chance) if chance is not None else None,
                rain_mm=float(rain) if rain is not None else None,
                wind_max=float(wind) if wind is not None else None,
            )
        )
    return days


# --- Textos (armados en código, sin IA) -------------------------------------


def day_line(forecast: DayForecast) -> str:
    """Por ejemplo: «🌧 lluvia débil, 9–17 °C, 80 % de probabilidad de lluvia (4,2 mm)»."""
    text = f"{forecast.emoji} {forecast.description}, {forecast.temp_min:.0f}–{forecast.temp_max:.0f} °C"
    if forecast.rain_chance is not None and forecast.rain_chance >= RAIN_WORTH_MENTIONING:
        text += f", {forecast.rain_chance} % de probabilidad de lluvia"
        if forecast.rain_mm:
            text += f" ({forecast.rain_mm:.1f} mm)".replace(".", ",")
    return text


def weather_text(report: WeatherReport, today: date, days: int = 3) -> str:
    """Para `/clima`: ahora y los próximos días."""
    lines = [f"Clima en {report.place.label}"]
    if report.current is not None:
        description, emoji = describe_code(report.current.code)
        lines.append(f"Ahora: {emoji} {report.current.temperature:.0f} °C, {description}")
    upcoming = [f for f in report.days if f.day >= today][:days]
    for forecast in upcoming:
        lines.append(f"- {_day_name(forecast.day, today)}: {day_line(forecast)}")
    lines.append("Fuente: Open-Meteo")
    return "\n".join(lines)


def forecast_to_dict(forecast: DayForecast) -> dict[str, Any]:
    """Para la tool: datos crudos, para que el modelo responda lo que se le preguntó."""
    return {
        "fecha": forecast.day.isoformat(),
        "dia": format_spanish_date(forecast.day),
        "descripcion": forecast.description,
        "min_c": round(forecast.temp_min),
        "max_c": round(forecast.temp_max),
        "prob_lluvia_pct": forecast.rain_chance,
        "lluvia_mm": forecast.rain_mm,
        "viento_max_kmh": round(forecast.wind_max) if forecast.wind_max is not None else None,
    }


def _day_name(day: date, today: date) -> str:
    delta = (day - today).days
    if delta == 0:
        return "Hoy"
    if delta == 1:
        return "Mañana"
    return format_spanish_date(day).capitalize()


# --- HTTP ----------------------------------------------------------------------


def http_get_json(url: str, timeout: float) -> Any:
    """GET verificado con el almacén de certificados del sistema (como el resto de JARVIS)."""
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "JARVIS"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise WeatherError(f"Open-Meteo no respondió bien ({exc.code}). Inténtalo más tarde.") from None
    except (urllib.error.URLError, OSError):
        raise WeatherError("No pude conectar con Open-Meteo para ver el clima (revisa tu conexión).") from None
    except ValueError:
        raise WeatherError("Open-Meteo devolvió una respuesta que no entiendo.") from None


@cache
def _ssl_context() -> ssl.SSLContext:
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
