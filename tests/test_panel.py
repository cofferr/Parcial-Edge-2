"""Pruebas del panel Streamlit con streamlit.testing (AppTest) y de sus consultas."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from edge_parcial.panel.consultas import (
    estado_componentes,
    evidencias,
    parte_de,
    ventanas_recientes,
)
from edge_parcial.panel.datos import Rutas
from edge_parcial.panel.estado import COMPONENTES, entrada, escribir_estado
from edge_parcial.panel.simulador import Simulador

APP = str(Path(__file__).resolve().parent.parent / "app" / "main.py")


@pytest.fixture
def datos(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path))
    return Rutas(base=tmp_path, snapshots=tmp_path / "snapshots")


def _correr() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception, at.exception
    return at


def _textos(at: AppTest) -> str:
    return " ".join(
        [i.value for i in at.info]
        + [m.value for m in at.markdown]
        + [s.value for s in at.subheader]
    )


def test_vivo_sin_ningun_dato(datos):
    at = _correr()
    assert [t.value for t in at.title] == ["Vivo"]
    info = " ".join(i.value for i in at.info)
    assert "Sin estado.json" in info
    assert "Sin lecturas" in info
    assert "Sin ventanas" in info
    assert "Sin evidencias" in info


def test_vivo_con_datos_simulados(datos):
    sim = Simulador(datos, semilla=3)
    for _ in range(30):
        sim.paso()
    at = _correr()
    assert not at.info  # ningún estado vacío
    assert {m.label for m in at.metric} == {"Temperatura", "Humedad", "PIR"}
    assert "camara_esp32" in _textos(at)
    assert any(
        type(e).__name__ == "Image" for e in at.main
    )  # la galería muestra evidencias


def test_mediciones_vacio_y_con_tablas(datos):
    at = AppTest.from_file(APP, default_timeout=30)
    at.switch_page("paginas/mediciones.py").run()
    assert not at.exception
    assert any("Sin resultados" in i.value for i in at.info)

    tablas = datos.tablas
    tablas.mkdir(parents=True)
    (tablas / "t1_4_tprop.csv").write_text("fuente,tprop_ms\nesp32,21.0\n")
    (tablas / "t2_x.csv").write_text("a\n1\n")
    (tablas / "t9_roto.csv").write_bytes(b"")
    at = AppTest.from_file(APP, default_timeout=30)
    at.switch_page("paginas/mediciones.py").run()
    assert not at.exception, at.exception
    assert [h.value for h in at.header] == ["Parte 1", "Parte 2", "Otras"]


def test_estado_obsoleto_es_sin_senal(tmp_path):
    ahora = datetime(2026, 10, 28, 12, 0).astimezone()
    reciente = (ahora - timedelta(seconds=1)).isoformat()
    vieja = (ahora - timedelta(seconds=30)).isoformat()
    escribir_estado(
        tmp_path / "estado.json",
        {"ble": entrada(True, None, reciente), "nucleo": entrada(True, None, vieja)},
    )
    v = {c.nombre: c for c in estado_componentes(tmp_path / "estado.json", ahora)}
    assert v["ble"].estado == "vivo"
    assert v["nucleo"].estado == "sin señal"
    assert v["camara_local"].estado == "sin datos"
    assert len(v) == len(COMPONENTES)


def test_estado_corrupto_no_rompe(tmp_path):
    (tmp_path / "estado.json").write_text("{no es json")
    assert all(
        c.estado == "sin datos" for c in estado_componentes(tmp_path / "estado.json")
    )


def test_ventanas_y_evidencias(datos):
    sim = Simulador(datos, semilla=4)
    for _ in range(25):
        sim.paso()
    tabla = ventanas_recientes(datos, n=10)
    assert list(tabla.index) == ["esp32", "droidcam", "local", "alerta"]
    assert tabla.shape[1] == 10
    items = evidencias(datos, n=5)
    assert items and len(items) <= 5
    # una referencia con ruta relativa maliciosa no sale de snapshots
    with open(datos.reconocimientos, "a") as f:
        f.write("2026-10-28T12:00:00-05:00,esp32,1,Ana,0.3,../estado.json\n")
    assert all(e.ruta.parent == datos.snapshots for e in evidencias(datos))


def test_parte_de():
    assert [
        parte_de(n) for n in ("t1_5_x.csv", "reto1_latencia.csv", "t3_a.csv", "z.csv")
    ] == [
        "Parte 1",
        "Parte 1",
        "Parte 3",
        "Otras",
    ]
