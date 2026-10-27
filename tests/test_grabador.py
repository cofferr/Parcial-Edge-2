"""Grabador guiado con fuentes simuladas (sin hardware)."""

import csv
import importlib.util
import itertools
import json
import sys

import pytest
from escenario import ServidorFalso, config_hacia, manejador_droidcam, manejador_esp32
from test_tres_fuentes import PantallaFalsa

from edge_parcial import metadata
from edge_parcial.acquisition.grabador import guion_estandar
from edge_parcial.acquisition.lector_local import CamaraSimulada
from edge_parcial.config import RAIZ


@pytest.fixture(autouse=True)
def sin_hardware(monkeypatch):
    monkeypatch.setattr(
        metadata, "leer_wifi_mac", lambda: {"tasa_transmision_mbps": 144.0}
    )


def cargar_script():
    espec = importlib.util.spec_from_file_location(
        "t1_6_grabar", RAIZ / "scripts" / "t1_6_grabar.py"
    )
    mod = importlib.util.module_from_spec(espec)
    sys.modules["t1_6_grabar"] = mod
    espec.loader.exec_module(mod)
    return mod


def camara(cfg):
    return CamaraSimulada(cfg.local.ancho, cfg.local.alto, intervalo_s=0.005)


def correr(tmp_path, pantalla, extra=()):
    with (
        ServidorFalso(manejador_esp32()) as s_esp,
        ServidorFalso(manejador_droidcam()) as s_dc,
    ):
        ruta = config_hacia(tmp_path, s_esp.puerto, s_dc.puerto)
        rc = cargar_script().main(
            ["--calibracion-s", "0.4", "--ciclos", "2", "--estatico-s", "0.3",
             "--actividad-s", "0.3", "--config", str(ruta), "--salida", str(tmp_path / "rec"),
             "--cpu-s", "0.1", "--confirmo-efectos-desactivados", *extra],
            camara_factory=camara, pantalla=pantalla,
        )  # fmt: skip
    carpeta = next((tmp_path / "rec").iterdir())
    return rc, carpeta


def test_guion_estandar():
    g = guion_estandar()
    assert [s.tipo for s in g] == ["calibracion"] + ["estatico", "actividad"] * 5
    assert sum(s.duracion_s for s in g) == 210.0


def test_grabacion_guarda_jpegs_segmentos_y_dibuja_en_el_hilo_principal(tmp_path):
    pantalla = PantallaFalsa()
    rc, carpeta = correr(tmp_path, pantalla)
    assert rc == 0
    with open(carpeta / "segmentos.csv", newline="") as f:
        segs = list(csv.DictReader(f))
    assert [s["tipo"] for s in segs] == [
        "calibracion",
        "estatico",
        "actividad",
        "estatico",
        "actividad",
    ]
    for a, b in itertools.pairwise(segs):
        assert int(a["t_ini_ns"]) < int(a["t_fin_ns"]) <= int(b["t_ini_ns"])
    for fuente in ("local", "esp32", "droidcam"):
        jpgs = sorted((carpeta / fuente).glob("*.jpg"))
        assert len(jpgs) > 5 and jpgs[0].read_bytes()[:2] == b"\xff\xd8"
    with open(carpeta / "frames.csv", newline="") as f:
        assert {r["source"] for r in csv.DictReader(f)} == {
            "local",
            "esp32",
            "droidcam",
        }
    meta = json.loads((carpeta / "metadata.json").read_text())
    assert (
        meta["contexto"]["tarea"] == "1.6" and meta["valida"] and not meta["abortada"]
    )
    assert pantalla.hilos == {"MainThread"} and pantalla.cerrada


def test_q_aborta_y_marca_invalida(tmp_path):
    pantalla = PantallaFalsa(teclas=[-1, -1, ord("q")])
    rc, carpeta = correr(tmp_path, pantalla)
    meta = json.loads((carpeta / "metadata.json").read_text())
    assert rc == 1 and meta["abortada"] and not meta["valida"]


def test_argumentos_invalidos(tmp_path):
    assert cargar_script().main(["--fuentes", "x"]) == 2
    assert cargar_script().main(["--config", str(tmp_path / "no.toml")]) == 2
