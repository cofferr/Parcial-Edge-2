"""Pruebas de la carga de configuración."""

import pytest

from edge_parcial.config import RUTA_EJEMPLO, ErrorConfig, cargar_config


def test_carga_ejemplo():
    cfg = cargar_config(RUTA_EJEMPLO)
    assert cfg.esp32.ip
    assert cfg.droidcam.puerto == 4747
    assert cfg.v_propagacion_m_s > 0
    assert cfg.local.indice_camara == 0


def test_archivo_ausente_indica_como_crearlo(tmp_path):
    with pytest.raises(ErrorConfig, match="config.example.toml"):
        cargar_config(tmp_path / "no_existe.toml")


def test_seccion_faltante(tmp_path):
    ruta = tmp_path / "c.toml"
    ruta.write_text('[red]\ngateway_ip = "1.2.3.4"\n')
    with pytest.raises(ErrorConfig, match=r"\[esp32\]"):
        cargar_config(ruta)


def test_clave_faltante(tmp_path):
    texto = RUTA_EJEMPLO.read_text().replace("gateway_ip", "otra_clave")
    ruta = tmp_path / "c.toml"
    ruta.write_text(texto)
    with pytest.raises(ErrorConfig, match="gateway_ip"):
        cargar_config(ruta)


def test_toml_invalido(tmp_path):
    ruta = tmp_path / "c.toml"
    ruta.write_text("esto no es toml [")
    with pytest.raises(ErrorConfig, match="TOML inválido"):
        cargar_config(ruta)
