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
