"""Pruebas del simulador y de los lectores tolerantes del contrato de datos."""

import json
from datetime import datetime

from edge_parcial.panel.datos import (
    COLUMNAS_EVENTOS,
    COLUMNAS_RECONOCIMIENTOS,
    COLUMNAS_TELEMETRIA,
    Rutas,
    leer_csv,
)
from edge_parcial.panel.estado import COMPONENTES, leer_estado
from edge_parcial.panel.simulador import Simulador


def _rutas(tmp_path):
    return Rutas(base=tmp_path, snapshots=tmp_path / "snapshots")


def test_simulador_escribe_todo_el_contrato(tmp_path):
    r = _rutas(tmp_path)
    sim = Simulador(r, semilla=1)
    for _ in range(40):
        sim.paso()
    tel, ev, rec = (
        leer_csv(r.telemetria),
        leer_csv(r.eventos),
        leer_csv(r.reconocimientos),
    )
    assert list(tel.columns) == COLUMNAS_TELEMETRIA and len(tel) == 40
    assert list(ev.columns) == COLUMNAS_EVENTOS and len(ev) == 40
    assert list(rec.columns) == COLUMNAS_RECONOCIMIENTOS and len(rec) > 0
    for nombre in rec["snapshot"]:
        assert (r.snapshots / nombre).is_file()
    assert set(leer_estado(r.estado)) == set(COMPONENTES)
    # alerta consistente con los votos
    assert all(
        (int(a) == 1) == (int(n) >= 2)
        for a, n in zip(ev["alerta"], ev["n_true"], strict=True)
    )


def test_estado_tiene_claves_fijas(tmp_path):
    r = _rutas(tmp_path)
    Simulador(r, semilla=2).paso(datetime(2026, 10, 28, 12, 0).astimezone())
    for entrada in json.loads(r.estado.read_text()).values():
        assert set(entrada) == {"vivo", "fps", "ultima_marca", "errores_recientes"}


def test_leer_csv_ignora_linea_incompleta_y_ausente(tmp_path):
    assert leer_csv(tmp_path / "no_existe.csv").empty
    ruta = tmp_path / "x.csv"
    ruta.write_text("a,b\n1,2\n3,4\n5")  # última línea sin salto final
    assert leer_csv(ruta)["a"].tolist() == ["1", "3"]
    ruta.write_text("a,b\n1,2\n3\n")  # menos columnas que la cabecera
    assert leer_csv(ruta)["a"].tolist() == ["1"]
    assert leer_csv(ruta, ultimas=0).empty
