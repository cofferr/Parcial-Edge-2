"""Reconocimiento sin alerta (presencia) y fila/foto de toda fuente que vota."""

import csv
import threading
import time
from datetime import datetime, timedelta

import cv2
import numpy as np
import pytest
from test_nucleo import cfg_p2

from edge_parcial.nucleo.config_p2 import FUENTES
from edge_parcial.nucleo.fuentes import EntradaSimulada
from edge_parcial.nucleo.nucleo import Nucleo
from edge_parcial.nucleo.reconocimiento import (
    DespachadorRostros,
    ReconocimientoContinuo,
)
from edge_parcial.panel.consultas import alerta_activa, presentes, unir_alertas
from edge_parcial.panel.datos import (
    COLUMNAS_EVENTOS,
    COLUMNAS_RECONOCIMIENTOS,
    EscritorCSV,
    Rutas,
    leer_csv,
)

CARA = {"top": 10, "right": 80, "bottom": 90, "left": 10}


def _jpeg() -> bytes:
    ok, buf = cv2.imencode(".jpg", np.full((120, 160, 3), 90, np.uint8))
    assert ok
    return buf.tobytes()


def _leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _despachador(tmp_path, consultar, ultimo=lambda f, e: _jpeg()):
    return DespachadorRostros(
        ultimo, tmp_path / "s", tmp_path / "r.csv", print, consultar
    )


def test_fuente_que_vota_sin_rostro_deja_foto_y_fila(tmp_path):
    d = _despachador(tmp_path, lambda j, f: [])  # la ESP32 no ve ninguna cara
    d.disparar(5, ["esp32"])
    d.esperar()
    [fila] = _leer(tmp_path / "r.csv")
    assert (fila["fuente"], fila["identidad"], fila["ventana_ref"]) == (
        "esp32",
        "sin_rostro",
        "5",
    )
    assert (tmp_path / "s" / fila["snapshot"]).read_bytes() == _jpeg()  # la foto queda


def test_continuo_registra_presencia_sin_alerta_y_no_repite(tmp_path):
    t = [0.0]
    d = _despachador(
        tmp_path, lambda j, f: [{"identidad": "Ana", "distancia": 0.3, "caja": CARA}]
    )
    c = ReconocimientoContinuo(
        d, ("esp32",), repetir_s=10, ventana_actual=lambda: 4, reloj=lambda: t[0]
    )
    c.una_pasada()
    t[0] = 3.0
    c.una_pasada()  # Ana sigue ahí: no se vuelve a anotar
    t[0] = 11.0
    c.una_pasada()  # pasaron 10 s: otra fila
    filas = _leer(tmp_path / "r.csv")
    assert [(f["identidad"], f["ventana_ref"]) for f in filas] == [
        ("Ana", "4"),
        ("Ana", "4"),
    ]


def test_continuo_sin_caras_o_sin_imagen_no_escribe_ni_falla(tmp_path):
    errores = []
    d = DespachadorRostros(
        lambda f, e: None,
        tmp_path / "s",
        tmp_path / "r.csv",
        errores.append,
        lambda j, f: [],
    )
    ReconocimientoContinuo(d, ("esp32",)).una_pasada()
    d2 = _despachador(tmp_path, lambda j, f: [])
    ReconocimientoContinuo(d2, ("esp32",)).una_pasada()
    assert _leer(tmp_path / "r.csv") == [] and errores == []


def test_continuo_con_servicio_caido_anota_error(tmp_path):
    errores = []

    def caido(j, f):
        raise ConnectionRefusedError("nadie")

    d = DespachadorRostros(
        lambda f, e: _jpeg(), tmp_path / "s", tmp_path / "r.csv", errores.append, caido
    )
    ReconocimientoContinuo(d, ("esp32",)).una_pasada()
    assert any("servicio de rostros" in e for e in errores)


def test_el_nucleo_reconoce_en_segundo_plano_aunque_no_haya_alerta(tmp_path):
    from test_nucleo import quieta

    entradas = {
        f: EntradaSimulada(f, quieta, fps=20) for f in FUENTES
    }  # nadie se mueve
    d = _despachador(
        tmp_path, lambda j, f: [{"identidad": "Ana", "distancia": 0.3, "caja": CARA}]
    )
    c = ReconocimientoContinuo(d, periodo_s=0.2)
    nuc = Nucleo(
        cfg_p2(),
        entradas,
        "t",
        tmp_path / "eventos.csv",
        None,
        consola=lambda _: None,
        despachador=d,
        continuo=c,
    )
    nuc.iniciar()
    time.sleep(1.5)
    nuc.detener()
    assert c._parar.is_set() and not any(
        h.name == "rostros-continuo" and h.is_alive() for h in threading.enumerate()
    )
    eventos = _leer(tmp_path / "eventos.csv")
    assert all(e["alerta"] == "0" for e in eventos)  # ninguna alerta...
    assert _leer(tmp_path / "r.csv")  # ...y aun así hay reconocimiento


@pytest.fixture
def rutas(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path))
    return Rutas(base=tmp_path, snapshots=tmp_path / "snapshots")


def _rec(rutas, ts, fuente, identidad, ventana=1, snap="x.jpg"):
    EscritorCSV(rutas.reconocimientos, COLUMNAS_RECONOCIMIENTOS).agregar(
        {
            "ts_wall": ts.isoformat(timespec="seconds"),
            "fuente": fuente,
            "ventana_ref": ventana,
            "identidad": identidad,
            "snapshot": snap,
            "session_id": "S",
        }
    )


def test_presentes_muestra_quien_se_ve_ahora(rutas):
    ahora = datetime.now().astimezone()
    _rec(rutas, ahora - timedelta(seconds=2), "local", "Ana")
    _rec(rutas, ahora - timedelta(seconds=3), "esp32", "desconocido")
    _rec(rutas, ahora - timedelta(seconds=1), "droidcam", "sin_rostro")
    _rec(rutas, ahora - timedelta(seconds=30), "droidcam", "Luis")  # ya no está
    assert presentes(rutas, ahora) == {
        "esp32": ["DESCONOCIDO"],
        "droidcam": [],
        "local": ["Ana"],
    }


def test_banner_distingue_sin_rostro_de_reconociendo(rutas):
    ahora = datetime.now().astimezone()
    EscritorCSV(rutas.eventos, COLUMNAS_EVENTOS).agregar(
        {
            "run_id": "r",
            "ts_wall": ahora.isoformat(timespec="seconds"),
            "ventana": 9,
            "n_true": 2,
            "Q": 2,
            "alerta": 1,
            "session_id": "S",
        }
    )
    assert alerta_activa(rutas, ahora + timedelta(seconds=1)).estado == "reconociendo"
    _rec(rutas, ahora, "esp32", "sin_rostro", ventana=9)
    a = alerta_activa(rutas, ahora + timedelta(seconds=1))
    assert (
        a.estado == "sin_rostro" and a.nombres == []
    )  # el servicio respondió: nadie a la vista
    _rec(rutas, ahora, "local", "Ana", ventana=9)
    assert alerta_activa(rutas, ahora + timedelta(seconds=1)).nombres == ["Ana"]
    union = unir_alertas(leer_csv(rutas.eventos), leer_csv(rutas.reconocimientos))
    assert list(union["reconocidos"]) == ["Ana"]
