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


def test_droidcam_sin_velocidad_nominal_fija():
    cfg = cargar_config(RUTA_EJEMPLO)
    assert cfg.droidcam.velocidad_nominal_bps is None


def test_esp32_velocidad_con_campo_fuente():
    cfg = cargar_config(RUTA_EJEMPLO)
    assert cfg.esp32.velocidad_nominal_bps == 72_200_000
    assert "MCS" in cfg.esp32.velocidad_nominal_fuente


def test_parametros_del_lector():
    lec = cargar_config(RUTA_EJEMPLO).lector
    assert (lec.backoff_inicial_s, lec.backoff_max_s) == (0.25, 4.0)
    assert (lec.intentos_max, lec.cola_max, lec.recv_bytes) == (5, 8, 65536)
    assert lec.warmup_fotogramas == 20


def test_falta_seccion_lector(tmp_path):
    texto = RUTA_EJEMPLO.read_text().split("[lector]")[0]
    ruta = tmp_path / "c.toml"
    ruta.write_text(texto)
    with pytest.raises(ErrorConfig, match=r"\[lector\]"):
        cargar_config(ruta)


def test_camara_local_en_config():
    loc = cargar_config(RUTA_EJEMPLO).local
    assert (loc.ancho, loc.alto, loc.jpeg_calidad) == (1920, 1080, 50)


def test_falta_clave_de_resolucion_local(tmp_path):
    texto = RUTA_EJEMPLO.read_text().replace("ancho = 1920", "otro = 1920")
    ruta = tmp_path / "c.toml"
    ruta.write_text(texto)
    with pytest.raises(ErrorConfig, match="ancho"):
        cargar_config(ruta)
