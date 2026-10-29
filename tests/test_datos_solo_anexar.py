"""Regla de datos: solo anexar, nada se borra ni se sobrescribe; sesiones y respaldo."""

import csv
import os
import stat
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from edge_parcial.ble.telemetria import COLUMNAS, EscritorTelemetria
from edge_parcial.ble.trama import decodificar
from edge_parcial.csv_anexar import copia_con_fecha, preparar_csv, ruta_libre
from edge_parcial.nucleo import salidas
from edge_parcial.panel.datos import (
    COLUMNAS_RECONOCIMIENTOS,
    EscritorCSV,
    Rutas,
)
from edge_parcial.panel.historico import filtrar, leer_historico, resumen, sesiones
from edge_parcial.panel.respaldo import respaldar
from edge_parcial.sesion import VARIABLE, sesion_actual

TRAMA = bytes.fromhex("9c 09 7a 17 ff ff 00")
PAGINA = str(Path(__file__).resolve().parent.parent / "app" / "paginas" / "datos.py")


def _filas(ruta):
    with open(ruta, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def test_reabrir_conserva_y_sigue_anexando(tmp_path):
    ruta = tmp_path / "t.csv"
    ts = datetime(2026, 10, 28, 20, 0, 0).astimezone()
    for _ in range(3):  # tres «arranques»
        EscritorTelemetria(ruta).agregar(ts, decodificar(TRAMA), TRAMA)
    filas = _filas(ruta)
    assert len(filas) == 1 + 3 and filas[0] == COLUMNAS
    assert [p.name for p in tmp_path.iterdir()] == ["t.csv"]  # ni copias ni truncados


def test_cabecera_distinta_aparta_el_archivo_viejo(tmp_path):
    ruta = tmp_path / "t.csv"
    ruta.write_text("a,b\n1,2\n3,4\n")
    assert preparar_csv(ruta, ["x", "y"]) is True
    aparte = [p for p in tmp_path.iterdir() if p.name != "t.csv"]
    assert len(aparte) == 1 and aparte[0].read_text() == "a,b\n1,2\n3,4\n"  # intacto
    assert not ruta.exists()  # el nuevo lo crea el escritor


def test_fila_a_medias_no_se_pega_con_la_nueva(tmp_path):
    ruta = tmp_path / "t.csv"
    ruta.write_text("a,b\n1,2\n3,")  # caída a mitad de una fila
    assert preparar_csv(ruta, ["a", "b"]) is False
    with open(ruta, "a") as f:
        f.write("5,6\n")
    assert ruta.read_text().splitlines() == ["a,b", "1,2", "3,", "5,6"]


def test_los_tres_csv_llevan_session_id(tmp_path, monkeypatch):
    monkeypatch.setenv(VARIABLE, "20261028-200000")
    assert sesion_actual() == "20261028-200000"
    ts = datetime(2026, 10, 28, 20, 0, 0).astimezone()
    EscritorTelemetria(tmp_path / "t.csv").agregar(ts, decodificar(TRAMA), TRAMA)
    EscritorCSV(tmp_path / "r.csv", COLUMNAS_RECONOCIMIENTOS).agregar(
        {"fuente": "esp32"}
    )
    e = salidas.EventosCSV(tmp_path / "e.csv", "run")
    e.cerrar()
    for nombre in ("t.csv", "r.csv"):
        cab, fila = _filas(tmp_path / nombre)
        assert cab[-1] == "session_id" and fila[-1] == "20261028-200000"
    assert _filas(tmp_path / "e.csv")[0][-1] == "session_id"


def test_ruta_libre_nunca_pisa(tmp_path):
    a = tmp_path / "foto.jpg"
    a.write_bytes(b"1")
    b = ruta_libre(a)
    b.write_bytes(b"2")
    assert (
        b.name == "foto_2.jpg"
        and ruta_libre(a).name == "foto_3.jpg"
        and a.read_bytes() == b"1"
    )


def test_copia_de_la_configuracion_antes_de_modificarla(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("x = 1\n")
    copia = copia_con_fecha(cfg)
    assert copia.read_text() == "x = 1\n" and copia.name.startswith("config.toml.bak-")
    assert copia_con_fecha(tmp_path / "no.toml") is None


def test_respaldo_copia_sin_mover_y_conserva_todas(tmp_path):
    base, rostros = tmp_path / "data", tmp_path / "rostros_conocidos"
    base.mkdir()
    (base / "telemetria.csv").write_text("a\n1\n")
    (base / "notas.txt").write_text("no csv")
    (rostros / "Ana").mkdir(parents=True)
    (rostros / "Ana" / "1.jpg").write_bytes(b"x")
    uno = respaldar(base, rostros, datetime(2026, 10, 28, 20, 0, 0))
    dos = respaldar(base, rostros, datetime(2026, 10, 28, 20, 0, 0))  # mismo segundo
    assert uno != dos and (uno / "telemetria.csv").read_text() == "a\n1\n"
    assert (uno / "rostros_conocidos" / "Ana" / "1.jpg").read_bytes() == b"x"
    assert not (uno / "notas.txt").exists()
    assert (base / "telemetria.csv").exists() and (
        rostros / "Ana" / "1.jpg"
    ).exists()  # nada se movió
    assert respaldar(tmp_path / "vacio", None) is None


def test_proteger_y_desbloquear(tmp_path):
    from scripts_proteger import bloqueada, bloquear, desbloquear

    raiz = tmp_path / "raw"
    (raiz / "corrida").mkdir(parents=True)
    f = raiz / "corrida" / "datos.csv"
    f.write_text("1")
    try:
        bloquear(raiz)
        assert bloqueada(raiz) and not os.access(f, os.W_OK)
        with pytest.raises(PermissionError):
            os.remove(f)
        with pytest.raises(PermissionError):
            (raiz / "corrida" / "nuevo.csv").write_text("x")
        with pytest.raises(PermissionError):
            f.write_text("sobrescrito")
        assert f.read_text() == "1"
    finally:
        desbloquear(raiz)
    assert os.access(f, os.W_OK) and stat.S_IMODE(raiz.stat().st_mode) & stat.S_IWUSR


def test_restaurar_no_sobrescribe(tmp_path):
    from scripts_restaurar import restaurar

    base, rostros = tmp_path / "data", tmp_path / "ros"
    copia = base / "_respaldo" / "20261028-200000"
    (copia / "rostros_conocidos" / "Ana").mkdir(parents=True)
    (copia / "rostros_conocidos" / "Ana" / "1.jpg").write_bytes(b"x")
    (copia / "a.csv").write_text("viejo\n")
    (copia / "b.csv").write_text("igual\n")
    (copia / "c.csv").write_text("perdido\n")
    base.mkdir(exist_ok=True)
    (base / "a.csv").write_text("actual\n")
    (base / "b.csv").write_text("igual\n")
    informe = dict(restaurar(copia, base, rostros))
    assert (base / "a.csv").read_text() == "actual\n"  # no se pisa
    assert informe["a.csv"].startswith("distinto") and informe["b.csv"] == "idéntico"
    assert (base / "c.csv").read_text() == "perdido\n" and informe["c.csv"] == "copiado"
    assert (base / "a.restaurado-20261028-200000.csv").read_text() == "viejo\n"
    assert (rostros / "Ana" / "1.jpg").read_bytes() == b"x"


# -- histórico y página --------------------------------------------------------------------


def _telemetria(ruta, sesion, dia, n):
    nuevo = not ruta.exists()
    with open(ruta, "a", newline="") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(COLUMNAS)
        for i in range(n):
            ts = (
                datetime(2026, 10, dia, 10, 0, i)
                .astimezone()
                .isoformat(timespec="seconds")
            )
            w.writerow([ts, "24.1", "60.0", "", 0, "", "aa", sesion])


def test_historico_etiqueta_filas_viejas_y_apartados(tmp_path):
    ruta = tmp_path / "telemetria.csv"
    (tmp_path / "telemetria.antes-20261027-090000.csv").write_text(
        "timestamp,temperatura_c,humedad_pct,suelo_adc,movimiento,foto,trama_hex\n"
        "2026-10-27T09:00:00-05:00,22,50,,0,,aa\n"
    )
    ruta.write_text(
        ",".join(COLUMNAS) + "\n2026-10-28T10:00:00-05:00,24,60,,0,,aa,S1\n"
        "2026-10-28T10:00:05-05:00,24,60,,0,,aa,S2\n2026-10-28T10:00:10-05:00,24,6"
    )
    actual = leer_historico(ruta)
    assert (
        sesiones(actual) == ["S2", "S1"] and len(actual) == 2
    )  # la fila a medias no cuenta
    todo = leer_historico(ruta, incluir_apartados=True)
    assert "previa 20261027-090000" in sesiones(todo) and len(todo) == 3
    n, desde = resumen(todo, "timestamp")
    assert n == 3 and desde.startswith("2026-10-27 09:00:00")
    una = filtrar(todo, "timestamp", sesion="S1")
    assert len(una) == 1
    rango = filtrar(
        todo, "timestamp", desde=date(2026, 10, 28), hasta=date(2026, 10, 28)
    )
    assert len(rango) == 2
    assert len(filtrar(todo, "timestamp", hasta=date(2026, 10, 27))) == 1


@pytest.fixture
def rutas(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EDGE_ORQUESTADO", "1")
    return Rutas(base=tmp_path, snapshots=tmp_path / "snapshots")


def test_pagina_datos_muestra_dos_sesiones(rutas):
    _telemetria(rutas.telemetria, "20261028-100000", 28, 4)
    _telemetria(rutas.telemetria, "20261028-150000", 28, 6)
    at = AppTest.from_file(PAGINA, default_timeout=30).run()
    assert not at.exception, at.exception
    assert any(
        "10 en el alcance" in c.value for c in at.caption
    )  # las dos sesiones juntas
    at.radio[0].set_value("Una sesión").run()
    opciones = at.selectbox(key="sesion_elegida").options
    assert opciones == ["20261028-150000", "20261028-100000"]
    at.selectbox(key="sesion_elegida").set_value("20261028-100000").run()
    assert any(c.value.startswith("4 filas en el filtro") for c in at.caption)
    at.selectbox(key="sesion_elegida").set_value("20261028-150000").run()
    assert any(c.value.startswith("6 filas en el filtro") for c in at.caption)


def test_ayer_y_hoy_no_se_mezclan_con_el_rango(rutas):
    ayer = (datetime.now() - timedelta(days=1)).day
    _telemetria(rutas.telemetria, "S", ayer, 3)
    assert (
        len(filtrar(leer_historico(rutas.telemetria), "timestamp", desde=date.today()))
        == 0
    )
