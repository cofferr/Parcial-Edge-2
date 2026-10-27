"""Pruebas del escritor único de CSV."""

import csv
import threading

import pytest

from edge_parcial.acquisition.modelo import (
    COLUMNAS_EVENTOS,
    COLUMNAS_FRAMES,
    evento_vacio,
    fila_vacia,
)
from edge_parcial.acquisition.registro import RegistroCSV


def leer(ruta):
    with open(ruta, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_encabezados_y_directorio(tmp_path):
    destino = tmp_path / "r1"
    RegistroCSV(destino).cerrar()
    assert (destino / "frames.csv").read_text().splitlines()[0] == ",".join(
        COLUMNAS_FRAMES
    )
    assert (destino / "eventos.csv").read_text().splitlines()[0] == ",".join(
        COLUMNAS_EVENTOS
    )


def test_columnas_del_prompt_maestro_y_adenda():
    minimas = [
        "run_id",
        "source",
        "endpoint",
        "condition",
        "seq",
        "warmup",
        "t_first_ns",
        "t_last_ns",
        "t_ready_ns",
        "payload_bytes",
        "header_bytes",
        "jpeg_valid",
        "width",
        "height",
        "capture_us",
        "flush_us",
        "jpeg_us",
        "rssi_dbm",
        "fw",
        "error",
        "t_request_ns",
        "t_decode_ini_ns",
        "n_recv",
        "bytes_recv_total",
        "conexion",
        "cabeceras_faltantes",
        "descartado",
    ]
    assert set(minimas) <= set(COLUMNAS_FRAMES)


def test_ns_sin_redondear_y_none_vacio(tmp_path):
    grande = 987654321098765432  # más de 2**53: un float lo redondearía
    with RegistroCSV(tmp_path) as reg:
        f = fila_vacia()
        f.update(
            run_id="r", source="esp32", seq=0, t_first_ns=grande, t_last_ns=grande + 1
        )
        reg.fila(f)
    fila = leer(tmp_path / "frames.csv")[0]
    assert int(fila["t_first_ns"]) == grande and int(fila["t_last_ns"]) == grande + 1
    assert fila["t_ready_ns"] == "" and fila["error"] == ""


def test_error_con_comas_y_saltos_se_conserva(tmp_path):
    with RegistroCSV(tmp_path) as reg:
        f = fila_vacia()
        f.update(run_id="r", error='a, "b"\nc')
        reg.fila(f)
    assert leer(tmp_path / "frames.csv")[0]["error"] == 'a, "b"\nc'


def test_eventos(tmp_path):
    with RegistroCSV(tmp_path) as reg:
        e = evento_vacio()
        e.update(
            run_id="r", source="esp32", tipo="corte", conexion=0, bytes_parciales=200
        )
        reg.evento(e)
    ev = leer(tmp_path / "eventos.csv")
    assert ev[0]["tipo"] == "corte" and ev[0]["bytes_parciales"] == "200"


def test_un_solo_escritor_con_muchos_hilos(tmp_path):
    n_hilos, por_hilo = 6, 300
    reg = RegistroCSV(tmp_path)

    def productor(k):
        for i in range(por_hilo):
            f = fila_vacia()
            f.update(run_id="r", source=f"s{k}", seq=i, error="x" * (i % 7))
            reg.fila(f)

    hilos = [threading.Thread(target=productor, args=(k,)) for k in range(n_hilos)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    reg.cerrar()
    filas = leer(tmp_path / "frames.csv")
    assert len(filas) == n_hilos * por_hilo
    for k in range(n_hilos):  # cada hilo conserva su orden y ninguna línea se mezcla
        propias = [int(f["seq"]) for f in filas if f["source"] == f"s{k}"]
        assert propias == list(range(por_hilo))
    assert all(len(f["error"]) == int(f["seq"]) % 7 for f in filas)


def test_columna_desconocida_se_rechaza(tmp_path):
    with RegistroCSV(tmp_path) as reg, pytest.raises(ValueError, match="otra"):
        reg.fila({"otra": 1})


def test_cerrar_vacia_la_cola(tmp_path):
    reg = RegistroCSV(tmp_path)
    for i in range(500):
        f = fila_vacia()
        f["seq"] = i
        reg.fila(f)
    reg.cerrar()
    assert len(leer(tmp_path / "frames.csv")) == 500


def test_error_de_escritura_se_propaga(tmp_path):
    reg = RegistroCSV(tmp_path)
    reg._cola.put(("f", {"clave_inexistente": 1}))  # DictWriter lo rechaza
    with pytest.raises(ValueError):
        reg.cerrar()
