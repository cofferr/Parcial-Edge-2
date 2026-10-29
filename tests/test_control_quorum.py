"""Paso 5: control.json (panel -> núcleo) y semántica de «quórum desactivado»."""

import csv
import json
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from test_nucleo import cfg_p2, movimiento

from edge_parcial.nucleo.config_p2 import FUENTES
from edge_parcial.nucleo.fuentes import EntradaSimulada
from edge_parcial.nucleo.nucleo import Nucleo
from edge_parcial.nucleo.reconocimiento import DespachadorRostros
from edge_parcial.panel.control import escribir_quorum_activo, quorum_activo
from edge_parcial.panel.datos import Rutas
from edge_parcial.panel.simulador import Simulador

APP = str(Path(__file__).resolve().parent.parent / "app" / "main.py")


def _leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_quorum_activo_por_defecto_y_ante_archivo_roto(tmp_path):
    assert quorum_activo(None) and quorum_activo(tmp_path / "no.json")
    roto = tmp_path / "c.json"
    roto.write_text('{"quorum_ac')
    assert quorum_activo(roto)
    roto.write_text("[1]")
    assert quorum_activo(roto)


def test_escritura_atomica_y_lectura(tmp_path):
    ruta = tmp_path / "control.json"
    escribir_quorum_activo(ruta, False)
    assert (
        quorum_activo(ruta) is False
        and json.loads(ruta.read_text())["quorum_activo"] is False
    )
    escribir_quorum_activo(ruta, True)
    assert quorum_activo(ruta) is True
    assert [p.name for p in tmp_path.iterdir()] == ["control.json"]  # sin temporales


def test_desactivado_registra_votos_marca_y_no_alerta_ni_reconoce(tmp_path):
    control = tmp_path / "control.json"
    escribir_quorum_activo(control, False)
    llamadas = []
    d = DespachadorRostros(
        lambda f, e: b"\xff\xd8", tmp_path / "s", tmp_path / "r.csv", print,
        lambda j, f: llamadas.append(f) or [],
    )  # fmt: skip
    entradas = {f: EntradaSimulada(f, movimiento, fps=20) for f in FUENTES}
    nuc = Nucleo(
        cfg_p2(), entradas, "t", tmp_path / "eventos.csv", None,
        consola=lambda _: None, despachador=d, ruta_control=control,
    )  # fmt: skip
    nuc.iniciar()
    time.sleep(2.6)
    nuc.detener()
    d.esperar()
    filas = _leer(tmp_path / "eventos.csv")
    estables = [f for f in filas if int(f["ventana"]) >= 2]
    assert estables and all(f["marca"] == "quorum_desactivado" for f in filas)
    assert all(f["alerta"] == "0" for f in filas)  # sin alertas
    assert all(f["n_true"] == "3" and f["Q"] == "2" for f in estables)  # votos intactos
    assert llamadas == []  # sin reconocimiento
    assert any(dec.alerta for dec in nuc.historial)  # la decisión medida no se altera


def test_reactivar_se_nota_en_la_ventana_siguiente(tmp_path):
    control = tmp_path / "control.json"
    escribir_quorum_activo(control, False)
    entradas = {f: EntradaSimulada(f, movimiento, fps=20) for f in FUENTES}
    nuc = Nucleo(
        cfg_p2(), entradas, "t", tmp_path / "eventos.csv", None,
        consola=lambda _: None, ruta_control=control,
    )  # fmt: skip
    nuc.iniciar()
    time.sleep(1.6)
    escribir_quorum_activo(control, True)
    time.sleep(1.6)
    nuc.detener()
    filas = _leer(tmp_path / "eventos.csv")
    assert filas[0]["marca"] == "quorum_desactivado" and filas[-1]["marca"] == ""
    assert filas[-1]["alerta"] == "1"


@pytest.fixture
def rutas(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EDGE_ORQUESTADO", "1")
    return Rutas(base=tmp_path, snapshots=tmp_path / "snapshots")


def test_simulador_respeta_el_control(rutas):
    escribir_quorum_activo(rutas.control, False)
    sim = Simulador(rutas, semilla=3)
    for _ in range(30):
        sim.paso()
    filas = _leer(rutas.eventos)
    assert all(f["alerta"] == "0" and f["marca"] == "quorum_desactivado" for f in filas)


def test_interruptor_de_la_barra_escribe_control_json(rutas):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception, at.exception
    assert quorum_activo(rutas.control)
    at.sidebar.toggle(key="quorum_activo").set_value(False).run()
    assert quorum_activo(rutas.control) is False
    assert any("DESACTIVADO" in w.value for w in at.sidebar.warning)
    assert "desactivado" in " ".join(m.value for m in at.sidebar.markdown)
