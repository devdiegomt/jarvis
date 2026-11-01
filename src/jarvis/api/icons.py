"""Íconos de la app (PNG) dibujados en código: un "reactor" cian sobre fondo azul noche.

Así el repositorio no guarda archivos binarios. iOS pide PNG para el ícono de la pantalla de inicio.
"""

import math
import struct
import zlib
from functools import cache

BACKGROUND = (11, 18, 32)
ACCENT = (56, 189, 248)
CORE = (224, 247, 255)


@cache
def icon_png(size: int) -> bytes:
    rows = []
    center = (size - 1) / 2
    for y in range(size):
        row = bytearray([0])  # filtro PNG "ninguno" en cada fila
        for x in range(size):
            row += bytes(_pixel(math.hypot(x - center, y - center) / size))
        rows.append(bytes(row))
    return _png(size, size, b"".join(rows))


def _pixel(distance: float) -> tuple[int, int, int]:
    """Color según la distancia al centro (en fracción del tamaño)."""
    color = BACKGROUND
    ring = max(0.0, 1 - abs(distance - 0.30) / 0.035)  # anillo
    glow = max(0.0, 1 - abs(distance - 0.30) / 0.12) * 0.35  # resplandor del anillo
    core = max(0.0, 1 - distance / 0.13)  # núcleo: cian en el borde, casi blanco al centro
    core_glow = max(0.0, 1 - distance / 0.2) * 0.5
    color = _mix(color, ACCENT, min(1.0, ring + glow + core_glow + (1.0 if core > 0 else 0.0)))
    return _mix(color, CORE, core**1.5)


def _mix(base: tuple[int, int, int], top: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(round(b + (t - b) * amount) for b, t in zip(base, top, strict=True))  # type: ignore[return-value]


def _png(width: int, height: int, raw: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8 bits, RGB
    signature = b"\x89PNG\r\n\x1a\n"
    return signature + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
