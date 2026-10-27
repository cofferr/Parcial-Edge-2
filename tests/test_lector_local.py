"""Pruebas del lector de cámara local con cámara simulada (sin hardware)."""

import json
import queue
import threading
import time
from itertools import pairwise

from test_lector_red import params

from edge_parcial.acquisition.lector_local import (
    ENDPOINT_LOCAL,
    CamaraSimulada,
    ItemCodificar,
    LectorLocal,
)


def correr(
    camara, n_total=25, p=None, ancho=None, alto=None, consumo_lento_s=0.0, espera=20.0
):
    p = p or params()
    props = camara.abrir()
    cola = queue.Queue(maxsize=p.cola_max)
    filas, eventos, hilos = [], [], set()

    def consumir():
        while (item := cola.get()) is not None:
            hilos.add(threading.current_thread().name)
            if consumo_lento_s:
                time.sleep(consumo_lento_s)
            filas.append(item.fila)

    consumidor = threading.Thread(target=consumir, name="consumidor", daemon=True)
    consumidor.start()
    lector = LectorLocal(
        camara,
        props,
        p,
        ancho or camara.ancho,
        alto or camara.alto,
        "r1",
        "aislada",
        cola,
        filas.append,
        eventos.append,
        n_total,
    )
    t0 = time.monotonic()
    lector.start()
    lector.join(espera)
    duracion = time.monotonic() - t0
    lector.detener()
    lector.join(5)
    cola.put(None)
    consumidor.join(5)
    filas.sort(key=lambda f: f["seq"])
    return filas, eventos, lector, duracion


def test_filas_del_lector_local():
    cam = CamaraSimulada(192, 108)
    filas, _, lector, _ = correr(cam, n_total=25)
    assert [f["seq"] for f in filas] == list(range(25))
    assert [f["warmup"] for f in filas] == [1] * 20 + [0] * 5
    assert {f["source"] for f in filas} == {"local"}
    assert {f["endpoint"] for f in filas} == {ENDPOINT_LOCAL}
    assert all(f["raw_bytes"] == 192 * 108 * 3 for f in filas)
    assert all((f["width"], f["height"]) == (192, 108) for f in filas)
    # Sin red: estos campos quedan vacíos.
    for col in (
        "t_first_ns",
        "t_last_ns",
        "n_recv",
        "header_bytes",
        "bytes_recv_total",
    ):
        assert all(f[col] is None for f in filas), col
    assert all(f["t_request_ns"] <= f["t_ready_ns"] for f in filas)
    ready = [f["t_ready_ns"] for f in filas]
    assert ready == sorted(ready)
    assert lector.resumen.fotogramas == 25 and lector.resumen.motivos_invalida() == []


def test_raw_bytes_a_resolucion_nativa_1920x1080():
    cam = CamaraSimulada(1920, 1080)
    filas, _, lector, _ = correr(cam, n_total=3)
    assert all(f["raw_bytes"] == 6_220_800 for f in filas)
    assert lector.resumen.resolucion_real == (1920, 1080)


def test_la_lectura_ocurre_en_otro_hilo_que_el_de_prueba():
    class Registra(CamaraSimulada):
        def __init__(self):
            super().__init__()
            self.hilos = set()

        def leer(self):
            self.hilos.add(threading.current_thread().name)
            return super().leer()

    cam = Registra()
    correr(cam, n_total=3)
    assert cam.hilos and threading.current_thread().name not in cam.hilos
    assert all(n.startswith("lector-local") for n in cam.hilos)


def test_evento_camara_abierta_con_propiedades():
    cam = CamaraSimulada(fps_reportado=29.97)
    _, eventos, *_ = correr(cam, n_total=1)
    e = next(e for e in eventos if e["tipo"] == "camara_abierta")
    detalle = json.loads(e["detalle"])
    assert detalle["fps_reportado"] == 29.97 and detalle["backend"] == "SIMULADA"
    assert detalle["ancho_solicitado"] == 192


def test_resolucion_real_distinta_invalida_la_fuente():
    cam = CamaraSimulada(1280, 720)
    _, eventos, lector, _ = correr(cam, n_total=2, ancho=1920, alto=1080)
    assert lector.resumen.resolucion_real == (1280, 720)
    assert lector.resumen.resolucion_solicitada == (1920, 1080)
    motivos = lector.resumen.motivos_invalida()
    assert len(motivos) == 1 and "1280x720" in motivos[0] and "1920x1080" in motivos[0]
    assert [e["tipo"] for e in eventos].count("resolucion_inesperada") == 1


def test_un_fallo_aislado_de_read_es_una_fila_con_error_y_sigue():
    cam = CamaraSimulada(fallos={3})
    filas, _, lector, _ = correr(cam, n_total=6)
    assert [f["error"] is None for f in filas] == [True, True, True, False, True, True]
    assert filas[3]["t_ready_ns"] is None and filas[3]["raw_bytes"] is None
    assert lector.resumen.errores == 1 and not lector.resumen.abandonada


def test_fallos_seguidos_abandonan_la_fuente():
    cam = CamaraSimulada(fallar_desde=2)
    filas, eventos, lector, _ = correr(cam, n_total=50, p=params(intentos_max=3))
    assert len(filas) == 5  # 2 buenas + 3 fallidas
    assert (
        lector.resumen.abandonada
        and "abandonada" in lector.resumen.motivos_invalida()[0]
    )
    assert [e["tipo"] for e in eventos].count("abandono") == 1


def test_consumidor_lento_descarta_sin_bloquear_la_lectura():
    cam = CamaraSimulada(intervalo_s=0.002)
    filas, _, lector, duracion = correr(
        cam, n_total=60, p=params(cola_max=2), consumo_lento_s=0.05
    )
    assert duracion < 2.0  # la lectura no esperó al consumidor
    assert [f["seq"] for f in filas] == list(range(60))
    descartados = [f for f in filas if f["descartado"] == 1]
    assert lector.resumen.descartes == len(descartados) > 0
    assert all(f["raw_bytes"] and f["t_ready_ns"] for f in descartados)


def test_el_item_lleva_el_fotograma_nativo():
    cam = CamaraSimulada(64, 48)
    props = cam.abrir()
    cola = queue.Queue(8)
    lector = LectorLocal(
        cam, props, params(), 64, 48, "r", "aislada", cola, print, lambda e: None, 1
    )
    lector.start()
    lector.join(5)
    item = cola.get_nowait()
    assert isinstance(item, ItemCodificar)
    assert item.frame.shape == (48, 64, 3) and item.frame.dtype.name == "uint8"


def test_detener_corta_la_lectura():
    cam = CamaraSimulada(intervalo_s=0.01)
    props = cam.abrir()
    lector = LectorLocal(
        cam,
        props,
        params(),
        192,
        108,
        "r",
        "aislada",
        queue.Queue(8),
        lambda f: None,
        lambda e: None,
    )
    lector.start()
    time.sleep(0.1)
    lector.detener()
    lector.join(2)
    assert not lector.is_alive()


def test_el_fps_no_se_fuerza_y_el_interarribo_sigue_a_la_camara():
    cam = CamaraSimulada(intervalo_s=0.02)
    filas, *_ = correr(cam, n_total=30)
    dif = [b["t_ready_ns"] - a["t_ready_ns"] for a, b in pairwise(filas)]
    mediana = sorted(dif)[len(dif) // 2] / 1e6
    assert 15 < mediana < 40  # ~20 ms: lo que entrega la cámara, sin paso extra
