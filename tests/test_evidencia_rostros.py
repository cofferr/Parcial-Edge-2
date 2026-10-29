"""Paso 2: evidencia del PIR desde el visor, eventos.csv ampliado y alerta -> rostros."""

import csv
import threading
import time
from datetime import datetime

from test_nucleo import cfg_p2, movimiento

from edge_parcial.ble import gateway as modulo_gateway
from edge_parcial.ble.gateway import Gateway, ParamsBle
from edge_parcial.ble.telemetria import EscritorTelemetria
from edge_parcial.nucleo import salidas
from edge_parcial.nucleo.config_p2 import FUENTES
from edge_parcial.nucleo.evidencia import LectorEvidenciaPIR
from edge_parcial.nucleo.fuentes import EntradaSimulada
from edge_parcial.nucleo.nucleo import Nucleo
from edge_parcial.nucleo.reconocimiento import DespachadorRostros


def _leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _trama(mov: int) -> bytes:
    return bytes.fromhex("9c 09 7a 17 ff ff") + bytes([mov])


def _gw(tmp_path, monkeypatch, jpeg):
    monkeypatch.setattr(modulo_gateway, "obtener_ultimo", lambda fuente, max_edad: jpeg)
    params = ParamsBle(fuente_foto="esp32", carpeta_fotos=tmp_path / "s")
    reloj = lambda: datetime(2026, 10, 28, 19, 0, 0).astimezone()
    return Gateway(
        None, EscritorTelemetria(tmp_path / "t.csv"), tmp_path / "e.json", params, reloj
    )


def test_ble_guarda_el_ultimo_fotograma_compartido(tmp_path, monkeypatch):
    gw = _gw(tmp_path, monkeypatch, b"\xff\xd8JPG")
    gw.al_recibir(_trama(1))
    gw.al_recibir(_trama(0))
    filas = (tmp_path / "t.csv").read_text().splitlines()
    assert "pir_esp32_20261028_190000.jpg" in filas[1] and "pir_" not in filas[2]
    assert (
        tmp_path / "s" / "pir_esp32_20261028_190000.jpg"
    ).read_bytes() == b"\xff\xd8JPG"


def test_ble_sin_fotograma_reciente_anota_error_y_no_lanza(tmp_path, monkeypatch):
    gw = _gw(tmp_path, monkeypatch, None)
    gw.al_recibir(_trama(1))  # no debe lanzar
    assert any("Sin fotograma reciente de esp32" in e for e in gw.errores)
    assert "pir_" not in (tmp_path / "t.csv").read_text()


def test_ble_no_abre_conexion_propia_a_la_camara():
    import inspect

    fuente = inspect.getsource(modulo_gateway)
    assert "urlopen" not in fuente and "cv2" not in fuente


def test_lector_evidencia_lee_filas_nuevas_y_tolera_linea_a_medias(tmp_path):
    ruta = tmp_path / "telemetria.csv"
    ruta.write_text(
        "timestamp,temperatura_c,humedad_pct,suelo_adc,movimiento,foto,trama_hex\n"
        "2026-10-28T19:00:00-05:00,24,60,,1,pir_droidcam_20261028_190000.jpg,aa\n"
        "2026-10-28T19:00:05-05:00,24,60,,0,,bb\n"
        "2026-10-28T19:00:10-05:00,24,60,,1,pir_es"  # a medio escribir
    )
    lector = LectorEvidenciaPIR(ruta)
    assert lector.nueva() == ("droidcam", "pir_droidcam_20261028_190000.jpg")
    assert lector.nueva() == ("", "")  # ya consumida
    assert LectorEvidenciaPIR(tmp_path / "no.csv").nueva() == ("", "")


def test_eventos_csv_nuevo_esquema_y_migracion_del_viejo(tmp_path):
    ruta = tmp_path / "eventos.csv"
    ruta.write_text(",".join(salidas.COLUMNAS_EVENTOS_V1) + "\nviejo\n")
    salidas.EventosCSV(ruta, "r").cerrar()
    assert ruta.read_text().splitlines()[0].split(",") == salidas.COLUMNAS_EVENTOS
    aparte = [p for p in tmp_path.iterdir() if ".v1-" in p.name]
    assert (
        len(aparte) == 1 and "viejo" in aparte[0].read_text()
    )  # el archivo viejo se conserva


def test_despachador_registra_caras_y_snapshot_sin_bloquear(tmp_path):
    errores = []
    esperar = threading.Event()

    def consultar(jpeg, fuente):
        esperar.wait(2)
        return [
            {"identidad": "Ana", "distancia": 0.31},
            {"identidad": "desconocido", "distancia": None},
        ]

    d = DespachadorRostros(
        lambda f, e: b"\xff\xd8x" if f != "local" else None,
        tmp_path / "snap",
        tmp_path / "reconocimientos.csv",
        errores.append,
        consultar,
    )
    t0 = time.perf_counter()
    d.disparar(7, ["esp32", "local"])
    assert time.perf_counter() - t0 < 0.1
    d.disparar(8, ["esp32"])  # el anterior sigue: se descarta, no se encola
    esperar.set()
    d.esperar()
    filas = list(_leer(tmp_path / "reconocimientos.csv"))
    assert [
        (f["fuente"], f["ventana_ref"], f["identidad"], f["distancia"]) for f in filas
    ] == [
        ("esp32", "7", "Ana", "0.31"),
        ("esp32", "7", "desconocido", ""),
    ]
    assert (tmp_path / "snap" / filas[0]["snapshot"]).read_bytes() == b"\xff\xd8x"
    assert any("sin fotograma reciente de local" in e for e in errores)
    assert any("descartado" in e for e in errores)


def test_servicio_caido_anota_error_y_no_lanza(tmp_path):
    errores = []

    def consultar(jpeg, fuente):
        raise ConnectionRefusedError("nadie")

    d = DespachadorRostros(
        lambda f, e: b"\xff\xd8",
        tmp_path,
        tmp_path / "r.csv",
        errores.append,
        consultar,
    )
    d.disparar(1, ["esp32"])
    d.esperar()
    assert any("servicio de rostros" in e for e in errores)


def test_alerta_del_nucleo_dispara_reconocimiento_y_escribe_reconocimientos(tmp_path):
    entradas = {f: EntradaSimulada(f, movimiento, fps=20) for f in FUENTES}
    llamadas = []

    def consultar(jpeg, fuente):
        llamadas.append(fuente)
        return [{"identidad": "Ana", "distancia": 0.4}]

    d = DespachadorRostros(
        lambda f, e: b"\xff\xd8x",
        tmp_path / "snap",
        tmp_path / "reconocimientos.csv",
        print,
        consultar,
    )
    nuc = Nucleo(
        cfg_p2(),
        entradas,
        "t",
        tmp_path / "eventos.csv",
        None,
        consola=lambda _: None,
        despachador=d,
    )
    nuc.iniciar()
    time.sleep(3.0)
    nuc.detener()
    d.esperar()
    assert llamadas and set(llamadas) <= set(FUENTES)
    rec = list(_leer(tmp_path / "reconocimientos.csv"))
    assert (
        rec
        and rec[0]["identidad"] == "Ana"
        and (tmp_path / "snap" / rec[0]["snapshot"]).exists()
    )


def test_eventos_registra_la_evidencia_del_pir(tmp_path):
    (tmp_path / "telemetria.csv").write_text(
        "timestamp,temperatura_c,humedad_pct,suelo_adc,movimiento,foto,trama_hex\n"
        "2026-10-28T19:00:00-05:00,24,60,,1,pir_esp32_20261028_190000.jpg,aa\n"
    )
    entradas = {f: EntradaSimulada(f, movimiento, fps=20) for f in FUENTES}
    nuc = Nucleo(
        cfg_p2(),
        entradas,
        "t",
        tmp_path / "eventos.csv",
        None,
        consola=lambda _: None,
        ruta_telemetria=tmp_path / "telemetria.csv",
    )
    nuc.iniciar()
    time.sleep(2.2)
    nuc.detener()
    filas = list(_leer(tmp_path / "eventos.csv"))
    con = [f for f in filas if f["evidencia_foto"]]
    assert len(con) == 1 and con[0]["evidencia_fuente"] == "esp32"
