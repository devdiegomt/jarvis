"""GET de APIs públicas que responden JSON (Open-Meteo, datos.gov.co), verificado con `truststore`."""

import json
import ssl
import urllib.error
import urllib.request
from functools import cache
from typing import Any


class NetError(Exception):
    """No se pudo consultar el servicio. El mensaje está pensado para el usuario."""


def get_json(url: str, timeout: float, service: str) -> Any:
    """`service` es el nombre que se muestra en los errores (por ejemplo, «Open-Meteo»)."""
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "JARVIS"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise NetError(f"{service} no respondió bien ({exc.code}). Inténtalo más tarde.") from None
    except (urllib.error.URLError, OSError):
        raise NetError(f"No pude conectar con {service} (revisa tu conexión).") from None
    except ValueError:
        raise NetError(f"{service} devolvió una respuesta que no entiendo.") from None


@cache
def _ssl_context() -> ssl.SSLContext:
    """Almacén de certificados del sistema operativo; la verificación nunca se desactiva."""
    import truststore

    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
