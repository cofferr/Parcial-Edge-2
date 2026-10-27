"""Pruebas del codificador JPEG de referencia."""

import queue
import threading

import cv2
import numpy as np

from edge_parcial.acquisition.codificador_jpeg import CodificadorJPEG
from edge_parcial.acquisition.lector_local import ItemCodificar
from edge_parcial.acquisition.modelo import fila_vacia


def item(frame, seq=0):
    fila = fila_vacia()
    fila.update(
        seq=seq, t_request_ns=1, t_ready_ns=2, raw_bytes=frame.nbytes, descartado=0
    )
    return ItemCodificar(fila, frame)


def correr(items, **kw):
    cola = queue.Queue(maxsize=len(items) + 1)
    filas = []
    cod = CodificadorJPEG(cola, filas.append, **kw)
    cod.start()
    for it in items:
        cola.put(it)
    cod.cerrar()
    assert not cod.is_alive()
    return filas, cod


def frame_aleatorio(alto=108, ancho=192, semilla=0):
    return np.random.default_rng(semilla).integers(
        0, 256, (alto, ancho, 3), dtype=np.uint8
    )


def test_tamano_igual_al_imencode_de_referencia_a_q50():
    fr = frame_aleatorio()
    filas, cod = correr([item(fr)], calidad=50)
    _, ref = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 50])
    assert filas[0]["payload_bytes"] == ref.size and filas[0]["jpeg_valid"] == 1
    assert cod.codificados == 1 and filas[0]["error"] is None


def test_la_calidad_se_aplica():
    fr = frame_aleatorio()
    q50, _ = correr([item(fr)], calidad=50)
    q90, _ = correr([item(fr)], calidad=90)
    assert q90[0]["payload_bytes"] > q50[0]["payload_bytes"]


def test_tiempos_de_codificacion_ordenados_y_sin_pisar_los_de_lectura():
    filas, _ = correr([item(frame_aleatorio())])
    f = filas[0]
    assert f["t_encode_ini_ns"] < f["t_encode_fin_ns"]
    assert (f["t_request_ns"], f["t_ready_ns"]) == (1, 2)  # el e2e no se toca
    assert f["raw_bytes"] == 192 * 108 * 3


def test_el_tiempo_cubre_solo_imencode(monkeypatch):
    """Entre t_encode_ini y t_encode_fin solo debe haber la llamada a imencode."""
    import edge_parcial.acquisition.codificador_jpeg as mod

    eventos = []
    real_encode = mod.cv2.imencode
    real_clock = mod.perf_counter_ns

    def reloj():
        eventos.append("reloj")
        return real_clock()

    def encode(*a, **k):
        eventos.append("imencode")
        return real_encode(*a, **k)

    monkeypatch.setattr(mod, "perf_counter_ns", reloj)
    monkeypatch.setattr(mod.cv2, "imencode", encode)
    correr([item(frame_aleatorio())])
    assert eventos == ["reloj", "imencode", "reloj"]


def test_codifica_en_otro_hilo_y_conserva_el_orden():
    hilos = []
    cola = queue.Queue()
    filas = []
    cod = CodificadorJPEG(
        cola, lambda f: (hilos.append(threading.current_thread()), filas.append(f))
    )
    cod.start()
    for i in range(10):
        cola.put(item(frame_aleatorio(semilla=i), seq=i))
    cod.cerrar()
    assert [f["seq"] for f in filas] == list(range(10))
    assert hilos[0] is not threading.main_thread()


def test_fotograma_nativo_1920x1080_bgr_sin_reducir():
    fr = np.zeros((1080, 1920, 3), np.uint8)
    filas, _ = correr([item(fr)], calidad=50)
    _, ref = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 50])
    assert filas[0]["raw_bytes"] == 6_220_800
    assert filas[0]["payload_bytes"] == ref.size
    jpeg = cv2.imdecode(ref, cv2.IMREAD_UNCHANGED)
    assert jpeg.shape == (1080, 1920, 3)  # color BGR, sin pasar a gris


def test_imencode_fallido_se_marca(monkeypatch):
    import edge_parcial.acquisition.codificador_jpeg as mod

    monkeypatch.setattr(mod.cv2, "imencode", lambda *a, **k: (False, None))
    filas, cod = correr([item(frame_aleatorio())])
    assert filas[0]["error"] == "imencode falló" and filas[0]["payload_bytes"] is None
    assert cod.fallidos == 1
