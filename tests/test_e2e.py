"""Tarea 1.5: latencia extremo a extremo medida contra servidores y cámara falsos."""

import csv
import importlib.util
import json
import sys

import pytest
from escenario import ServidorFalso, config_hacia, manejador_droidcam, manejador_esp32

from edge_parcial import metadata
from edge_parcial.acquisition.lector_local import CamaraSimulada
from edge_parcial.acquisition.lector_red import LectorAperturaStream
from edge_parcial.config import RAIZ

PAUSA_REAL_S = LectorAperturaStream.PAUSA_MIN_S


@pytest.fixture(autouse=True)
def sin_hardware(monkeypatch):
    monkeypatch.setattr(
        metadata, "leer_wifi_mac", lambda: {"tasa_transmision_mbps": 144.0}
    )
    # el servidor falso no necesita la pausa que exige DroidCam real
    monkeypatch.setattr(LectorAperturaStream, "PAUSA_MIN_S", 0.0)


def cargar_script():
    espec = importlib.util.spec_from_file_location(
        "t1_5_e2e", RAIZ / "scripts" / "t1_5_e2e.py"
    )
    mod = importlib.util.module_from_spec(espec)
    sys.modules["t1_5_e2e"] = mod
    espec.loader.exec_module(mod)
    return mod


def camara(cfg):
    return CamaraSimulada(cfg.local.ancho, cfg.local.alto, intervalo_s=0.002)


def correr(tmp_path, n=8, fuentes="esp32,droidcam,local"):
    with (
        ServidorFalso(manejador_esp32()) as s_esp,
        ServidorFalso(manejador_droidcam()) as s_dc,
    ):
        ruta = config_hacia(tmp_path, s_esp.puerto, s_dc.puerto)
        rc = cargar_script().main(
            ["--n", str(n), "--fuentes", fuentes, "--config", str(ruta),
             "--salida", str(tmp_path / "raw"), "--pausa-s", "0", "--cpu-s", "0.1",
             "--confirmo-efectos-desactivados"],
            camara_factory=camara,
        )  # fmt: skip
    metas = [
        json.loads(p.read_text())
        for p in sorted((tmp_path / "raw").glob("*/metadata.json"))
    ]
    return rc, metas


def filas(tmp_path, meta):
    with open(tmp_path / "raw" / meta["run_id"] / "frames.csv", newline="") as f:
        return list(csv.DictReader(f))


def test_un_run_por_fuente_con_contexto_1_5(tmp_path):
    rc, metas = correr(tmp_path)
    assert rc == 0 and len(metas) == 3
    assert {m["contexto"]["fuente"] for m in metas} == {"esp32", "droidcam", "local"}
    assert all(m["contexto"]["tarea"] == "1.5" and m["valida"] for m in metas)
    metodos = {m["contexto"]["fuente"]: m["contexto"]["metodo_e2e"] for m in metas}
    assert metodos["local"].startswith("read()")


def test_esp32_capture_abre_una_conexion_por_muestra(tmp_path):
    _, metas = correr(tmp_path, fuentes="esp32")
    filas_esp = filas(tmp_path, metas[0])
    medidas = [r for r in filas_esp if r["warmup"] == "0"]
    assert len(medidas) == 8 and {r["endpoint"] for r in filas_esp} == {"/capture"}
    assert len({r["conexion"] for r in filas_esp}) == len(filas_esp)
    for r in medidas:
        assert int(r["t_request_ns"]) < int(r["t_first_ns"]) <= int(r["t_last_ns"]) <= int(r["t_ready_ns"])  # fmt: skip
        assert r["flush_us"] != "" and r["capture_us"] != ""


def test_droidcam_e2e_desde_la_apertura_hasta_el_primer_fotograma(tmp_path):
    _, metas = correr(tmp_path, fuentes="droidcam")
    medidas = [r for r in filas(tmp_path, metas[0]) if r["warmup"] == "0"]
    assert len(medidas) == 8 and all(r["jpeg_valid"] == "1" for r in medidas)
    assert all(int(r["t_ready_ns"]) > int(r["t_request_ns"]) for r in medidas)
    assert len({r["conexion"] for r in medidas}) == len(
        medidas
    )  # una apertura por muestra


def test_local_e2e_es_read(tmp_path):
    _, metas = correr(tmp_path, fuentes="local")
    medidas = [r for r in filas(tmp_path, metas[0]) if r["warmup"] == "0"]
    assert len(medidas) == 8 and {r["endpoint"] for r in medidas} == {"cv2.read"}


def test_argumentos_invalidos(tmp_path):
    mod = cargar_script()
    assert mod.main(["--fuentes", "x"]) == 2
    assert mod.main(["--config", str(tmp_path / "no.toml")]) == 2


def test_muchos_errores_invalidan_la_fuente():
    from edge_parcial.acquisition.modelo import Resumen

    r = Resumen("droidcam", "/video")
    r.sumar(fotogramas=100, errores=10)
    assert any("con error" in m for m in r.motivos_invalida())
    ok = Resumen("droidcam", "/video")
    ok.sumar(fotogramas=100, errores=3)
    assert not ok.motivos_invalida()


def test_apertura_droidcam_impone_pausa_minima():
    assert PAUSA_REAL_S >= 0.5  # DroidCam libera el stream en <= 0,5 s
