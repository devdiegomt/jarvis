"""Configuración común de los tests."""

from pathlib import Path

import pytest

from jarvis import config


@pytest.fixture(autouse=True)
def isolated_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Ningún test escribe en ~/.config/jarvis: la carpeta por defecto pasa a ser temporal."""
    directory = tmp_path / "config"
    monkeypatch.setattr(config, "DEFAULT_CONFIG_DIR", directory)
    return directory


@pytest.fixture(autouse=True)
def no_public_apis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ningún test llama a APIs públicas reales (Open-Meteo, datos.gov.co): sin red, como en la CI."""
    from jarvis import net

    def offline(_url: str, _timeout: float, service: str) -> None:
        raise net.NetError(f"No pude conectar con {service} (sin red en los tests).")

    monkeypatch.setattr(net, "get_json", offline)
