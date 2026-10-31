"""Tool de clima con Open-Meteo: gratis y con datos exactos, sin gastar una búsqueda en internet."""

import json
from collections.abc import Callable
from datetime import datetime

from jarvis.tools.registry import Tool
from jarvis.weather import WeatherError, WeatherService, describe_code, forecast_to_dict

MAX_DAYS = 7


def build_tool(weather: WeatherService, now: Callable[[], datetime]) -> Tool:
    def get_clima(dias: int = 1) -> str:
        days = int(dias)
        if not 1 <= days <= MAX_DAYS:
            raise ValueError(f"dias debe estar entre 1 y {MAX_DAYS}.")
        try:
            report = weather.report()
        except WeatherError as exc:
            raise ValueError(f"{exc} Si el usuario insiste, puedes buscarlo en internet.") from exc
        today = now().date()
        result: dict[str, object] = {
            "lugar": report.place.label,
            "dias": [forecast_to_dict(f) for f in report.days if f.day >= today][:days],
            "fuente": "Open-Meteo",
        }
        if report.current is not None:
            result["ahora"] = {
                "temperatura_c": round(report.current.temperature),
                "descripcion": describe_code(report.current.code)[0],
            }
        return json.dumps(result, ensure_ascii=False)

    return Tool(
        name="get_clima",
        description=(
            "Clima de la ciudad del usuario: ahora y el pronóstico de los próximos días (temperatura "
            "mínima y máxima, probabilidad y cantidad de lluvia, viento). Úsala para cualquier pregunta "
            "de clima, lluvia o temperatura en su ciudad, en vez de buscar en internet. Para otras "
            "ciudades, busca en internet."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "dias": {
                    "type": "integer",
                    "description": (
                        f"Cuántos días desde hoy (1 = solo hoy, 2 = hoy y mañana; máximo {MAX_DAYS})."
                    ),
                }
            },
            "additionalProperties": False,
        },
        func=get_clima,
    )
