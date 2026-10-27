"""Pruebas del hilo decodificador."""

import queue
import threading
import time

import cv2
import numpy as np
from servidor_falso import hacer_jpeg

from edge_parcial.acquisition.decodificador import Decodificador
from edge_parcial.acquisition.lector_red import ItemDecodificar
from edge_parcial.acquisition.modelo import fila_vacia


def item(jpeg: bytes, t_last: int = 0, decodificar: bool = True, seq: int = 0):
    fila = fila_vacia()
    fila.update(seq=seq, t_first_ns=t_last - 1, t_last_ns=t_last, descartado=0)
    return ItemDecodificar(fila, jpeg, decodificar)


def correr(items, **kw):
    cola = queue.Queue(maxsize=max(8, len(items) + 1))
    filas = []
    dec = Decodificador(cola, filas.append, **kw)
    dec.start()
    for it in items:
        cola.put(it)
    dec.cerrar()
    assert not dec.is_alive()
    return filas, dec


def test_decodifica_y_sella_tiempos_en_orden():
    t_last = time.perf_counter_ns()
    filas, dec = correr([item(hacer_jpeg(1, 80, 60), t_last)])
    f = filas[0]
    assert (f["width"], f["height"]) == (80, 60)
    assert f["t_last_ns"] <= f["t_decode_ini_ns"] <= f["t_ready_ns"]
    assert f["error"] is None and dec.decodificados == 1


def test_resolucion_observada_de_un_jpeg_grande():
    ok, buf = cv2.imencode(".jpg", np.zeros((720, 1280, 3), np.uint8))
    assert ok
    filas, _ = correr([item(buf.tobytes())])
    assert (filas[0]["width"], filas[0]["height"]) == (1280, 720)


def test_jpeg_invalido_no_se_decodifica():
    filas, dec = correr([item(b"basura", decodificar=False)])
    f = filas[0]
    assert f["t_ready_ns"] is None and f["t_decode_ini_ns"] is None
    assert "inválido" in f["error"] and dec.fallidos == 1


def test_imdecode_devuelve_none_deja_t_ready_vacio_y_conserva_el_error_previo():
    malo = b"\xff\xd8" + b"\x12\x34" * 20 + b"\xff\xd9"
    it = item(malo)
    it.fila["error"] = "previo"
    filas, dec = correr([it])
    f = filas[0]
    assert f["t_ready_ns"] is None and f["t_decode_ini_ns"] is not None
    assert f["error"] == "previo; imdecode devolvió None" and dec.fallidos == 1


def test_conserva_el_orden_y_procesa_todo_antes_de_cerrar():
    items = [item(hacer_jpeg(i), seq=i) for i in range(30)]
    filas, _ = correr(items)
    assert [f["seq"] for f in filas] == list(range(30))


def test_el_decodificador_corre_en_otro_hilo():
    hilos = []
    cola = queue.Queue()
    dec = Decodificador(cola, lambda f: hilos.append(threading.current_thread()))
    dec.start()
    cola.put(item(hacer_jpeg(1)))
    dec.cerrar()
    assert hilos and hilos[0] is not threading.main_thread()


def test_escala_de_grises_con_flags():
    _, buf = cv2.imencode(".jpg", np.zeros((24, 32), np.uint8))
    filas, _ = correr([item(buf.tobytes())], flags=cv2.IMREAD_GRAYSCALE)
    assert (filas[0]["width"], filas[0]["height"]) == (32, 24)
