"""Visor MJPEG: servidor (ranuras sin cola, stream, sin señal) y publicador sin bloqueo."""

import threading
import time

import cv2
import numpy as np
import pytest
import uvicorn
from fastapi.testclient import TestClient

from edge_parcial.visor import cliente
from edge_parcial.visor.cliente import PublicadorVisor, obtener_ultimo, publicar_una_vez
from edge_parcial.visor.servidor import crear_app


def _jpeg(valor: int = 100) -> bytes:
    ok, buf = cv2.imencode(".jpg", np.full((24, 32, 3), valor, np.uint8))
    assert ok
    return buf.tobytes()


def test_publicar_y_ultimo():
    c = TestClient(crear_app())
    assert c.get("/ultimo/esp32.jpg").status_code == 404  # nada publicado
    assert c.post("/publicar/esp32", content=_jpeg()).status_code == 204
    r = c.get("/ultimo/esp32.jpg")
    assert (
        r.status_code == 200 and r.content == _jpeg()
    )  # payload intacto, sin re-codificar


def test_rechaza_lo_que_no_es_jpeg_y_fuentes_ajenas():
    c = TestClient(crear_app())
    assert c.post("/publicar/esp32", content=b"hola").status_code == 400
    assert c.post("/publicar/otra", content=_jpeg()).status_code == 404


def test_fotograma_viejo_ya_no_es_reciente():
    c = TestClient(crear_app(max_edad_s=0.2))
    c.post("/publicar/local", content=_jpeg())
    time.sleep(0.4)
    assert c.get("/ultimo/local.jpg").status_code == 404


def test_stream_es_multipart_y_reenvia_el_payload():
    c = TestClient(crear_app())
    c.post("/publicar/droidcam", content=_jpeg(50))
    with c.stream("GET", "/stream/droidcam") as r:
        assert r.headers["content-type"].startswith("multipart/x-mixed-replace")
        trozo = next(r.iter_bytes())
    assert b"--frame" in trozo and _jpeg(50) in trozo


def test_stream_sin_fotograma_muestra_sin_senal():
    c = TestClient(crear_app())
    with c.stream("GET", "/stream/esp32") as r:
        trozo = next(r.iter_bytes())
    assert b"image/jpeg" in trozo  # el marcador «sin señal» es un JPEG


@pytest.fixture
def visor_real():
    app = crear_app()
    cfg = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    srv = uvicorn.Server(cfg)
    hilo = threading.Thread(target=srv.run, daemon=True)
    hilo.start()
    while not srv.started:
        time.sleep(0.02)
    puerto = srv.servers[0].sockets[0].getsockname()[1]
    yield puerto
    srv.should_exit = True
    hilo.join(3)


def test_publicador_no_bloquea_y_llega_al_visor(visor_real):
    pub = PublicadorVisor(puerto=visor_real)
    pub.iniciar()
    t0 = time.perf_counter()
    for i in range(200):
        pub.publicar_jpeg("esp32", _jpeg(i % 200))
    assert time.perf_counter() - t0 < 0.1  # publicar solo asigna una referencia
    pub.publicar_jpeg("esp32", _jpeg(7))
    for _ in range(50):
        if obtener_ultimo("esp32", puerto=visor_real) == _jpeg(7):
            break
        time.sleep(0.05)
    pub.detener()
    assert obtener_ultimo("esp32", puerto=visor_real) == _jpeg(7)  # solo el último


def test_publicador_con_visor_caido_no_lanza():
    pub = PublicadorVisor(puerto=1)  # nadie escucha
    pub.iniciar()
    pub.publicar_jpeg("local", _jpeg())
    time.sleep(0.3)
    pub.detener()
    assert pub.errores and publicar_una_vez("local", _jpeg(), puerto=1) is False
    assert pub.ultimo("local") == _jpeg()  # sigue disponible dentro del proceso


def test_codificador_periodico_publica_la_local():
    pub = PublicadorVisor(puerto=1)
    img = np.full((48, 64, 3), 90, np.uint8)
    pub.codificar_periodico("local", lambda: img, fps=50)
    time.sleep(0.2)
    pub.detener()
    assert pub.ultimo("local")[:2] == b"\xff\xd8"
    assert cliente.CALIDAD_LOCAL == 70
