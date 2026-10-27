"""Pruebas de los lectores de red contra un servidor falso (sin hardware)."""

import logging
import queue
import socket
import threading
import time

from servidor_falso import (
    ServidorFalso,
    cabecera_http,
    cabeceras_esp32,
    enviar,
    hacer_jpeg,
    parte,
    respuesta_captura,
)

from edge_parcial.acquisition.lector_red import LectorCapture, LectorStream, SpecFuente
from edge_parcial.config import ParamsLector

ESP_STREAM = ("x-capture-us", "x-jpeg-us", "x-rssi-dbm")
ESP_CAPTURE = (*ESP_STREAM, "x-flush-us")


def params(**kw) -> ParamsLector:
    base = {
        "backoff_inicial_s": 0.02,
        "backoff_max_s": 0.1,
        "intentos_max": 3,
        "cola_max": 8,
        "recv_bytes": 65536,
        "timeout_conexion_s": 1.0,
        "timeout_inactividad_s": 0.5,
        "warmup_fotogramas": 20,
    }
    base.update(kw)
    return ParamsLector(**base)


def esperar_cliente(conn, maximo=10.0):
    """Mantiene abierta la conexión hasta que el cliente la cierre."""
    conn.settimeout(maximo)
    try:
        while conn.recv(1024):
            pass
    except OSError:
        pass


def correr(
    manejador,
    clase=LectorStream,
    ruta="/stream",
    source="esp32",
    esperadas=(),
    n_total=5,
    p=None,
    consumo_lento_s=0.0,
    espera=10.0,
    puerto=None,
    **kw,
):
    p = p or params()
    cola = queue.Queue(maxsize=p.cola_max)
    filas, eventos = [], []
    lock = threading.Lock()

    def sink_fila(f):
        with lock:
            filas.append(f)

    def sink_evento(e):
        with lock:
            eventos.append(e)

    def consumir():
        while True:
            item = cola.get()
            if item is None:
                return
            if consumo_lento_s:
                time.sleep(consumo_lento_s)
            sink_fila(item.fila)

    consumidor = threading.Thread(target=consumir, daemon=True)
    consumidor.start()
    srv = ServidorFalso(manejador)
    with srv:
        spec = SpecFuente(source, "127.0.0.1", puerto or srv.puerto, ruta, esperadas)
        lector = clase(
            spec,
            p,
            "r1",
            "aislada",
            "fw-test",
            cola,
            sink_fila,
            sink_evento,
            n_total,
            **kw,
        )
        t0 = time.monotonic()
        lector.start()
        lector.join(espera)
        duracion = time.monotonic() - t0
        vivo = lector.is_alive()
        lector.detener()
        lector.join(5)
    cola.put(None)
    consumidor.join(5)
    filas.sort(key=lambda f: f["seq"])
    return filas, eventos, lector.resumen, srv, duracion, vivo


def guion_stream(jpegs, trozo=0, pausa=0.0, con_cl=True, cab=None, mantener=True):
    def manejador(conn, req, n):
        enviar(conn, cabecera_http(), trozo, pausa)
        for i, j in enumerate(jpegs):
            c = cab(i) if cab else None
            enviar(conn, parte(j, con_cl=con_cl, cabeceras=c), trozo, pausa)
        if mantener:
            esperar_cliente(conn)

    return manejador


# -- /stream ---------------------------------------------------------------


def test_stream_completo_con_cabeceras_esp32():
    jpegs = [hacer_jpeg(i) for i in range(25)]
    filas, _, res, srv, _, vivo = correr(
        guion_stream(jpegs, trozo=700, cab=cabeceras_esp32),
        esperadas=ESP_STREAM,
        n_total=25,
    )
    assert not vivo
    assert [f["seq"] for f in filas] == list(range(25))
    assert [f["payload_bytes"] for f in filas] == [len(j) for j in jpegs]
    assert [f["warmup"] for f in filas] == [1] * 20 + [0] * 5
    assert all(f["jpeg_valid"] == 1 and f["error"] is None for f in filas)
    assert all(f["t_request_ns"] < f["t_first_ns"] <= f["t_last_ns"] for f in filas)
    assert len({f["t_request_ns"] for f in filas}) == 1  # mismo valor en la conexión
    assert {f["conexion"] for f in filas} == {0}
    assert {f["endpoint"] for f in filas} == {"/stream"}
    assert filas[3]["capture_us"] == 1003 and filas[3]["jpeg_us"] == 2003
    assert filas[3]["rssi_dbm"] == -53
    assert all(
        f["flush_us"] is None and f["cabeceras_faltantes"] is None for f in filas
    )
    assert {f["fw"] for f in filas} == {"fw-test"}
    assert all(f["n_recv"] >= 1 for f in filas)
    assert "Connection: keep-alive" in srv.peticiones[0]
    assert srv.peticiones[0].startswith("GET /stream HTTP/1.1")
    assert res.fotogramas == 25 and res.motivos_invalida() == []


def test_bytes_recv_total_coincide_con_lo_enviado():
    jpegs = [hacer_jpeg(i) for i in range(6)]
    enviado = len(cabecera_http()) + sum(len(parte(j)) for j in jpegs)
    filas, _, res, *_ = correr(guion_stream(jpegs, trozo=500), n_total=6)
    assert enviado - 2 <= filas[-1]["bytes_recv_total"] <= enviado  # CRLF final aparte
    assert res.bytes_recv_total == res.bytes_recv_por_conexion[0] <= enviado


def test_cabeceras_ausentes_se_marcan_y_se_advierten_una_vez(caplog):
    jpegs = [hacer_jpeg(i) for i in range(5)]
    with caplog.at_level(logging.WARNING, logger="edge_parcial.lector"):
        filas, _, res, *_ = correr(guion_stream(jpegs), esperadas=ESP_STREAM, n_total=5)
    assert all(f["capture_us"] is None and f["rssi_dbm"] is None for f in filas)
    assert all(
        f["cabeceras_faltantes"] == "X-Capture-Us;X-Jpeg-Us;X-Rssi-Dbm" for f in filas
    )
    assert res.cabeceras_faltantes == {
        "X-Capture-Us": 5,
        "X-Jpeg-Us": 5,
        "X-Rssi-Dbm": 5,
    }
    assert len(res.advertencias) == 3
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 3
    assert "cabeceras obligatorias ausentes" in res.motivos_invalida()[0]


def test_una_sola_cabecera_ausente():
    def cab(i):
        c = cabeceras_esp32(i)
        del c["X-Jpeg-Us"]
        return c

    filas, *_ = correr(
        guion_stream([hacer_jpeg(1)] * 3, cab=cab), esperadas=ESP_STREAM, n_total=3
    )
    assert all(
        f["cabeceras_faltantes"] == "X-Jpeg-Us" and f["jpeg_us"] is None for f in filas
    )
    assert all(f["capture_us"] is not None for f in filas)


def test_cabecera_no_entera_cuenta_como_faltante():
    def cab(i):
        return {**cabeceras_esp32(i), "X-Jpeg-Us": "abc"}

    filas, *_ = correr(
        guion_stream([hacer_jpeg(1)], cab=cab), esperadas=ESP_STREAM, n_total=1
    )
    assert (
        filas[0]["jpeg_us"] is None and filas[0]["cabeceras_faltantes"] == "X-Jpeg-Us"
    )


def test_droidcam_sin_content_length_ni_cabeceras():
    jpegs = [hacer_jpeg(i, 96, 72) for i in range(8)]
    filas, _, res, srv, *_ = correr(
        guion_stream(jpegs, trozo=333, con_cl=False),
        ruta="/video",
        source="droidcam",
        n_total=8,
    )
    assert [f["payload_bytes"] for f in filas] == [len(j) for j in jpegs]
    assert all(f["jpeg_valid"] == 1 and f["cabeceras_faltantes"] is None for f in filas)
    assert {f["endpoint"] for f in filas} == {"/video"}
    assert res.motivos_invalida() == []
    assert srv.peticiones[0].startswith("GET /video HTTP/1.1")


def test_corte_a_mitad_de_stream_reconecta_y_marca():
    a = [hacer_jpeg(i) for i in range(3)]
    b = [hacer_jpeg(10 + i) for i in range(3)]
    cortado = parte(hacer_jpeg(99))

    def manejador(conn, req, n):
        if n == 0:
            enviar(
                conn, cabecera_http() + b"".join(parte(j) for j in a) + cortado[:200]
            )
            return  # cierra a mitad del 4.º fotograma
        enviar(conn, cabecera_http() + b"".join(parte(j) for j in b))
        esperar_cliente(conn)

    filas, eventos, res, srv, *_ = correr(manejador, n_total=6)
    assert [f["seq"] for f in filas] == list(range(6))
    assert [f["conexion"] for f in filas] == [0, 0, 0, 1, 1, 1]
    assert [f["payload_bytes"] for f in filas] == [
        len(j) for j in a + b
    ]  # sin el parcial
    assert filas[0]["t_request_ns"] != filas[3]["t_request_ns"]
    tipos = [e["tipo"] for e in eventos]
    assert tipos.count("conexion_abierta") == 2 and "reintento" in tipos
    corte = next(e for e in eventos if e["tipo"] == "corte")
    assert corte["bytes_parciales"] == 200 and corte["conexion"] == 0
    assert corte["bytes_recv_total"] > 200
    assert res.reconexiones == 1 and len(res.bytes_recv_por_conexion) == 2
    assert len(srv.peticiones) == 2


def test_abandono_tras_agotar_reintentos():
    def manejador(conn, req, n):
        return  # cierra de inmediato

    filas, eventos, res, srv, _, vivo = correr(
        manejador, n_total=10, p=params(intentos_max=3)
    )
    assert not vivo and filas == []
    assert res.abandonada and "abandonada" in res.motivos_invalida()[0]
    assert [e["tipo"] for e in eventos].count("abandono") == 1
    assert res.reconexiones == 2 and len(srv.peticiones) == 3


def test_backoff_exponencial_acotado():
    def manejador(conn, req, n):
        return

    _, eventos, *_ = correr(manejador, n_total=10, p=params(intentos_max=6))
    esperas = [e["detalle"] for e in eventos if e["tipo"] == "reintento"]
    assert esperas == [
        "espera 0.02 s",
        "espera 0.04 s",
        "espera 0.08 s",
        "espera 0.1 s",
        "espera 0.1 s",
    ]


def test_servidor_inalcanzable_abandona():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()  # nadie escucha
    filas, eventos, res, *_ = correr(lambda *a: None, puerto=puerto, n_total=3)
    assert filas == [] and res.abandonada
    assert any(
        "Refused" in (e["detalle"] or "") for e in eventos if e["tipo"] == "corte"
    )


def test_inactividad_se_trata_como_corte_y_reconecta():
    def manejador(conn, req, n):
        enviar(conn, cabecera_http() + parte(hacer_jpeg(n)))
        esperar_cliente(conn)  # silencio

    filas, eventos, *_ = correr(
        manejador, n_total=2, p=params(timeout_inactividad_s=0.3)
    )
    assert [f["conexion"] for f in filas] == [0, 1]
    assert any(
        "sin datos" in (e["detalle"] or "") for e in eventos if e["tipo"] == "corte"
    )


def test_consumidor_lento_descarta_sin_bloquear_el_socket():
    jpegs = [hacer_jpeg(i) for i in range(40)]
    filas, _, res, _, duracion, vivo = correr(
        guion_stream(jpegs), n_total=40, p=params(cola_max=2), consumo_lento_s=0.05
    )
    assert not vivo and duracion < 1.5  # el lector no esperó al consumidor
    assert [f["seq"] for f in filas] == list(range(40))  # ninguna fila se pierde
    descartados = [f for f in filas if f["descartado"] == 1]
    assert res.descartes == len(descartados) > 0
    assert all(f["t_first_ns"] and f["t_last_ns"] for f in descartados)


def test_ultimo_trozo_retrasado_50ms_se_ve_en_ttx():
    j = hacer_jpeg(1, 128, 96)
    p = parte(j)

    def manejador(conn, req, n):
        enviar(conn, cabecera_http() + p[:-100])
        time.sleep(0.05)
        enviar(conn, p[-100:])
        esperar_cliente(conn)

    filas, *_ = correr(manejador, n_total=1)
    ttx = filas[0]["t_last_ns"] - filas[0]["t_first_ns"]
    assert ttx >= 45_000_000
    assert filas[0]["n_recv"] >= 2


def test_retardo_en_el_primer_trozo_no_se_atribuye_a_ttx():
    j = hacer_jpeg(1, 128, 96)

    def manejador(conn, req, n):
        time.sleep(0.05)  # el retardo ocurre ANTES del trozo que trae el boundary
        enviar(conn, cabecera_http() + parte(j), trozo=400)
        esperar_cliente(conn)

    filas, *_ = correr(manejador, n_total=1)
    f = filas[0]
    assert f["t_first_ns"] - f["t_request_ns"] >= 45_000_000  # queda antes de t_first
    assert f["t_last_ns"] - f["t_first_ns"] < 40_000_000  # y no entra en ttx


def test_detener_es_rapido_aunque_no_lleguen_datos():
    def manejador(conn, req, n):
        esperar_cliente(conn)

    cola = queue.Queue(8)
    with ServidorFalso(manejador) as srv:
        spec = SpecFuente("esp32", "127.0.0.1", srv.puerto, "/stream")
        lector = LectorStream(
            spec,
            params(timeout_inactividad_s=30),
            "r",
            "aislada",
            None,
            cola,
            print,
            lambda e: None,
        )
        lector.start()
        time.sleep(0.2)
        t0 = time.monotonic()
        lector.detener()
        lector.join(3)
        assert not lector.is_alive() and time.monotonic() - t0 < 1.0


# -- /capture --------------------------------------------------------------


def guion_capture(n_jpegs=20, con_cl=True, cab=None, trozo=0):
    def manejador(conn, req, n):
        j = hacer_jpeg(n % n_jpegs)
        enviar(conn, respuesta_captura(j, con_cl, cab(n) if cab else None), trozo)

    return manejador


def test_capture_una_conexion_nueva_por_muestra():
    filas, _, res, srv, *_ = correr(
        guion_capture(cab=lambda i: cabeceras_esp32(i, flush=True), trozo=300),
        clase=LectorCapture,
        ruta="/capture",
        esperadas=ESP_CAPTURE,
        n_total=5,
    )
    assert [f["seq"] for f in filas] == list(range(5))
    assert len(srv.peticiones) == 5
    assert all("Connection: close" in r for r in srv.peticiones)
    assert all(r.startswith("GET /capture HTTP/1.1") for r in srv.peticiones)
    assert [f["conexion"] for f in filas] == list(range(5))
    assert all(f["t_request_ns"] < f["t_first_ns"] <= f["t_last_ns"] for f in filas)
    assert filas[2]["flush_us"] == 32 and filas[2]["capture_us"] == 1002
    assert {f["endpoint"] for f in filas} == {"/capture"}
    assert all(f["cabeceras_faltantes"] is None and f["error"] is None for f in filas)
    assert res.motivos_invalida() == []


def test_capture_sin_flush_se_marca_como_faltante():
    filas, _, res, *_ = correr(
        guion_capture(cab=cabeceras_esp32),
        clase=LectorCapture,
        ruta="/capture",
        esperadas=ESP_CAPTURE,
        n_total=2,
    )
    assert all(f["cabeceras_faltantes"] == "X-Flush-Us" for f in filas)
    assert res.motivos_invalida()


def test_capture_sin_content_length_termina_al_cerrar():
    filas, *_ = correr(
        guion_capture(con_cl=False, trozo=200),
        clase=LectorCapture,
        ruta="/capture",
        n_total=3,
    )
    expect = [len(hacer_jpeg(i)) for i in range(3)]
    assert [f["payload_bytes"] for f in filas] == expect
    assert all(f["jpeg_valid"] == 1 for f in filas)


def test_capture_timeout_es_una_fila_con_error():
    def manejador(conn, req, n):
        time.sleep(1.5)  # acepta y no responde

    filas, _, res, _, duracion, _ = correr(
        manejador,
        clase=LectorCapture,
        ruta="/capture",
        n_total=2,
        p=params(timeout_inactividad_s=0.3),
    )
    assert len(filas) == 2 and duracion < 3
    assert all("TimeoutError" in f["error"] for f in filas)
    assert all(f["t_first_ns"] is None and f["payload_bytes"] is None for f in filas)
    assert all(f["t_request_ns"] is not None for f in filas)
    assert res.errores == 2 and [f["seq"] for f in filas] == [0, 1]


def test_capture_http_error_y_cierre_sin_respuesta():
    def manejador(conn, req, n):
        if n == 0:
            enviar(conn, b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")

    filas, *_ = correr(manejador, clase=LectorCapture, ruta="/capture", n_total=2)
    assert "HTTP 404" in filas[0]["error"]
    assert "ConnectionError" in filas[1]["error"]


def test_capture_no_reconecta_y_sigue_con_la_siguiente():
    def manejador(conn, req, n):
        if n == 1:
            return  # falla solo esa muestra
        enviar(conn, respuesta_captura(hacer_jpeg(n)))

    filas, eventos, res, *_ = correr(
        manejador, clase=LectorCapture, ruta="/capture", n_total=3
    )
    assert [f["error"] is None for f in filas] == [True, False, True]
    assert eventos == [] and res.reconexiones == 0
