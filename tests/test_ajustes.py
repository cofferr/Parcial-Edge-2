"""Pruebas de la edición de IP desde el panel."""

import pytest

from edge_parcial.config import RAIZ, ErrorConfig
from edge_parcial.panel.ajustes import guardar_ips, leer_ips, validar_ip


@pytest.fixture
def config(tmp_path):
    ruta = tmp_path / "config.toml"
    ruta.write_text(
        (RAIZ / "config" / "config.example.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return ruta


def test_guardar_cambia_solo_las_dos_ip(config):
    antes = config.read_text(encoding="utf-8")
    guardar_ips("10.0.0.5", "10.0.0.6", config)
    despues = config.read_text(encoding="utf-8")
    assert leer_ips(config) == {"esp32": "10.0.0.5", "droidcam": "10.0.0.6"}
    assert 'gateway_ip = "192.168.43.1"' in despues
    assert "# puerta de enlace del hotspot" in despues
    assert len(antes.splitlines()) == len(despues.splitlines())


def test_ip_invalida_no_toca_el_archivo(config):
    antes = config.read_text(encoding="utf-8")
    with pytest.raises(ErrorConfig):
        guardar_ips("999.1.1.1", "10.0.0.6", config)
    assert config.read_text(encoding="utf-8") == antes


def test_validar_ip_recorta_espacios():
    assert validar_ip(" 192.168.1.2 ") == "192.168.1.2"


def test_leer_sin_config_devuelve_vacias(tmp_path):
    assert leer_ips(tmp_path / "no.toml") == {"esp32": "", "droidcam": ""}
