"""Página Datos: filtros y tolerancia a archivos a medias."""

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from edge_parcial.panel.consultas import (
    filtrar_eventos,
    filtrar_reconocimientos,
    valores_distintos,
)
from edge_parcial.panel.datos import Rutas
from edge_parcial.panel.simulador import Simulador

PAGINA = str(Path(__file__).resolve().parent.parent / "app" / "paginas" / "datos.py")


@pytest.fixture
def rutas(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EDGE_ORQUESTADO", "1")
    return Rutas(base=tmp_path, snapshots=tmp_path / "snapshots")


def test_filtros_de_eventos():
    df = pd.DataFrame(
        {
            "voto_esp32": ["1", "0", "1"],
            "voto_droidcam": ["0", "0", "1"],
            "alerta": ["0", "0", "1"],
            "marca": ["", "quorum_desactivado", ""],
        }
    )
    assert len(filtrar_eventos(df, solo_alertas=True)) == 1
    assert len(filtrar_eventos(df, fuente="droidcam")) == 1
    assert len(filtrar_eventos(df, marca="quorum_desactivado")) == 1
    assert len(filtrar_eventos(df, marca="(sin marca)")) == 2
    assert valores_distintos(df, "marca") == ["quorum_desactivado"]
    assert filtrar_eventos(pd.DataFrame()).empty


def test_filtros_de_reconocimientos():
    df = pd.DataFrame(
        {"fuente": ["esp32", "local"], "identidad": ["Ana", "desconocido"]}
    )
    assert len(filtrar_reconocimientos(df, fuente="local")) == 1
    assert len(filtrar_reconocimientos(df, identidad="Ana")) == 1


def test_pagina_sin_archivos(rutas):
    at = AppTest.from_file(PAGINA, default_timeout=30).run()
    assert not at.exception, at.exception
    assert len([i for i in at.info if i.value.startswith("Sin ")]) == 3


def test_pagina_con_datos_y_ultima_linea_a_medias(rutas):
    sim = Simulador(rutas, semilla=2)
    for _ in range(25):
        sim.paso()
    with open(rutas.telemetria, "a") as f:
        f.write("2026-10-28T19:00:00-05:00,24.1,5")  # fila a medias, sin salto de línea
    at = AppTest.from_file(PAGINA, default_timeout=30).run()
    assert not at.exception, at.exception
    assert len(at.dataframe) >= 2 and not any(
        i.value.startswith("Sin ") for i in at.info
    )
