"""Alerta visible, ventanas con marca de tiempo y página Historial."""

import csv
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from edge_parcial.panel.consultas import alerta_activa, unir_alertas, ventanas_recientes
from edge_parcial.panel.datos import (
    COLUMNAS_EVENTOS,
    COLUMNAS_RECONOCIMIENTOS,
    EscritorCSV,
    Rutas,
    leer_csv,
)

APP = str(Path(__file__).resolve().parent.parent / "app" / "main.py")
HISTORIAL = str(
    Path(__file__).resolve().parent.parent / "app" / "paginas" / "historial.py"
)


@pytest.fixture
def rutas(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EDGE_ORQUESTADO", "1")
    return Rutas(base=tmp_path, snapshots=tmp_path / "snapshots")


def _ev(rutas, ts, ventana, votos=(1, 1, 0), alerta=1, sesion="S1"):
    EscritorCSV(rutas.eventos, COLUMNAS_EVENTOS).agregar(
        {
            "run_id": "r", "ts_wall": ts.isoformat(timespec="seconds"), "ventana": ventana,
            "voto_esp32": votos[0], "voto_droidcam": votos[1], "voto_local": votos[2],
            "Q": 2, "n_true": sum(votos), "alerta": alerta, "session_id": sesion,
        }
    )  # fmt: skip


def _rec(rutas, ts, ventana, identidad, snapshot="", sesion="S1"):
    EscritorCSV(rutas.reconocimientos, COLUMNAS_RECONOCIMIENTOS).agregar(
        {
            "ts_wall": ts.isoformat(timespec="seconds"), "fuente": "esp32",
            "ventana_ref": ventana, "identidad": identidad, "distancia": "",
            "snapshot": snapshot, "session_id": sesion,
        }
    )  # fmt: skip


def test_sin_alerta_no_hay_banner(rutas):
    ahora = datetime.now().astimezone()
    _ev(rutas, ahora, 1, votos=(0, 0, 0), alerta=0)
    assert alerta_activa(rutas) is None


def test_alerta_con_nombre_desconocido_y_estados(rutas):
    ahora = datetime.now().astimezone()
    _ev(rutas, ahora, 7)
    a = alerta_activa(rutas, ahora + timedelta(seconds=2))
    assert a.estado == "reconociendo" and a.nombres == [] and a.n_true == 2
    assert alerta_activa(rutas, ahora + timedelta(seconds=8)).estado == "sin_rostro"
    _rec(rutas, ahora, 7, "Ana")
    _rec(rutas, ahora, 7, "desconocido")
    a = alerta_activa(rutas, ahora + timedelta(seconds=3))
    assert a.estado == "identificado" and a.nombres == ["Ana", "DESCONOCIDO"]


def test_la_alerta_se_apaga_a_los_diez_segundos_y_no_mezcla_sesiones(rutas):
    ahora = datetime.now().astimezone()
    _ev(rutas, ahora, 7)
    _rec(rutas, ahora, 7, "Ana", sesion="OTRA")  # misma ventana, otra sesión
    assert alerta_activa(rutas, ahora + timedelta(seconds=1)).nombres == []
    assert alerta_activa(rutas, ahora + timedelta(seconds=11)) is None


def test_el_banner_aparece_en_todas_las_paginas_y_la_pagina_se_pone_roja(rutas):
    ahora = datetime.now().astimezone()
    _ev(rutas, ahora, 3)
    _rec(rutas, ahora, 3, "desconocido")
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception, at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "ALERTA · QUÓRUM CUMPLIDO" in html and "DESCONOCIDO" in html
    assert ".stApp { background: #3d0a0a" in html  # toda la pantalla cambia
    assert 'img[src*="/stream/"]' in html  # las cámaras se enmarcan en rojo
    # sin alerta, nada de eso
    (rutas.base / "eventos.csv").unlink()
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert "ALERTA · QUÓRUM CUMPLIDO" not in " ".join(m.value for m in at.markdown)


def test_nombre_con_html_se_escapa(rutas):
    ahora = datetime.now().astimezone()
    _ev(rutas, ahora, 3)
    _rec(rutas, ahora, 3, "<b>x</b>")
    at = AppTest.from_file(APP, default_timeout=30).run()
    html = " ".join(m.value for m in at.markdown)
    assert "&lt;b&gt;x&lt;/b&gt;" in html and "<b>x</b>" not in html


def test_ventanas_llevan_marca_de_tiempo(rutas):
    _ev(rutas, datetime(2026, 10, 28, 20, 12, 3).astimezone(), 14)
    tabla = ventanas_recientes(rutas)
    assert list(tabla.columns) == ["20:12:03 #14"]


def test_unir_alertas_asocia_reconocimientos(rutas):
    t0 = datetime(2026, 10, 28, 20, 0, 0).astimezone()
    _ev(rutas, t0, 1)
    _ev(rutas, t0 + timedelta(seconds=1), 2, votos=(1, 0, 0), alerta=0)
    _ev(rutas, t0 + timedelta(seconds=60), 1, sesion="S2")  # misma ventana, otra sesión
    _rec(rutas, t0 + timedelta(seconds=2), 1, "Ana", "esp32_a.jpg")
    union = unir_alertas(leer_csv(rutas.eventos), leer_csv(rutas.reconocimientos))
    assert list(union["reconocidos"]) == ["Ana", "—"] and list(union["votaron"]) == ["esp32+droidcam"] * 2  # fmt: skip
    assert union.iloc[0]["snapshot"] == "esp32_a.jpg"


def test_pagina_historial_con_dos_sesiones(rutas):
    t0 = datetime(2026, 10, 28, 20, 0, 0).astimezone()
    for i in range(5):
        _ev(
            rutas,
            t0 + timedelta(seconds=i),
            i,
            alerta=int(i == 2),
            sesion="20261028-200000",
        )
    for i in range(3):
        _ev(
            rutas,
            t0 + timedelta(minutes=30, seconds=i),
            i,
            alerta=0,
            sesion="20261028-203000",
        )
    _rec(rutas, t0 + timedelta(seconds=2), 2, "Ana", sesion="20261028-200000")
    at = AppTest.from_file(HISTORIAL, default_timeout=30).run()
    assert not at.exception, at.exception
    assert [m.value for m in at.metric][:2] == ["8", "1"]  # 8 ventanas, 1 alerta
    at.radio(key="hist_alcance").set_value("Una sesión").run()
    at.selectbox(key="hist_sesion").set_value("20261028-203000").run()
    assert [m.value for m in at.metric][:2] == ["3", "0"]
    assert any("No hubo alertas" in i.value for i in at.info)


def test_columnas_de_eventos_siguen_el_contrato(rutas):
    _ev(rutas, datetime.now().astimezone(), 1)
    with open(rutas.eventos, encoding="utf-8") as f:
        assert next(csv.reader(f)) == COLUMNAS_EVENTOS
