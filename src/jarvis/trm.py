"""TRM (dólar en Colombia) del día, de datos.gov.co (Superintendencia Financiera): gratis y sin clave.

Las conversiones se calculan en código; el modelo solo las pide y las cuenta.
"""

import threading
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from jarvis.money import format_money
from jarvis import net

TRM_URL = "https://www.datos.gov.co/resource/32sa-8pi3.json"
CACHE_SECONDS = 3 * 60 * 60
TIMEOUT_SECONDS = 10

FetchJson = Callable[[str, float], Any]


class TrmError(Exception):
    """No se pudo consultar la TRM. El mensaje está pensado para el usuario."""


@dataclass(frozen=True)
class Trm:
    value: Decimal  # pesos por dólar
    valid_from: date
    valid_to: date

    @property
    def line(self) -> str:
        return f"TRM: {format_money(self.value, 'USD').removesuffix(' USD')} por dólar"


class TrmService:
    """TRM vigente en una fecha, con caché en memoria (compartido entre hilos)."""

    def __init__(self, fetch: FetchJson | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self._fetch = fetch or _fetch
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[date, tuple[float, Trm]] = {}

    def on(self, day: date) -> Trm:
        """La TRM vigente ese día. Lanza TrmError si no se pudo consultar."""
        with self._lock:
            cached = self._cache.get(day)
            if cached is not None and self._clock() - cached[0] < CACHE_SECONDS:
                return cached[1]
            trm = self._query(day)
            self._cache[day] = (self._clock(), trm)
            return trm

    def line(self, day: date) -> str | None:
        """Para el resumen y `/hoy`: None si no está disponible."""
        try:
            return self.on(day).line
        except TrmError:
            return None

    def _query(self, day: date) -> Trm:
        moment = f"{day.isoformat()}T00:00:00.000"
        params = {
            "$select": "valor,vigenciadesde,vigenciahasta",
            "$where": f"vigenciadesde <= '{moment}' AND vigenciahasta >= '{moment}'",
            "$order": "vigenciadesde DESC",
            "$limit": "1",
        }
        rows = self._fetch(f"{TRM_URL}?{urllib.parse.urlencode(params)}", TIMEOUT_SECONDS)
        if not isinstance(rows, list) or not rows:
            raise TrmError(f"Todavía no hay TRM publicada para el {day:%d/%m/%Y}.")
        row = rows[0]
        try:
            return Trm(
                value=Decimal(str(row["valor"])),
                valid_from=datetime.fromisoformat(row["vigenciadesde"]).date(),
                valid_to=datetime.fromisoformat(row["vigenciahasta"]).date(),
            )
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise TrmError("datos.gov.co devolvió una TRM que no entiendo.") from None


def convert(amount: Decimal, currency: str, trm: Trm) -> tuple[Decimal, str]:
    """Convierte entre dólares y pesos con la TRM. Devuelve (monto, moneda de destino)."""
    if currency == "USD":
        return amount * trm.value, "COP"
    if currency == "COP":
        return amount / trm.value, "USD"
    raise TrmError("Con la TRM solo se convierte entre dólares (USD) y pesos (COP).")


def _fetch(url: str, timeout: float) -> Any:
    try:
        return net.get_json(url, timeout, "datos.gov.co")
    except net.NetError as exc:
        raise TrmError(f"{exc} No pude consultar la TRM.") from None
