"""Escenario de pruebas: ESP32 y DroidCam falsos (sockets) + config apuntando a ellos."""

import json
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
from test_lector_red import esperar_cliente

from edge_parcial.config import RUTA_EJEMPLO


def manejador_esp32(fw="T1", sin_cabeceras=False, pausa=0.004, capture_espera_s=0.0):
    jpegs = [hacer_jpeg(i, 64, 48) for i in range(12)]

    def manejador(conn, req, n):
        if req.startswith("GET /status"):
            cuerpo = json.dumps({"fw": fw, "rssi": -55}).encode()
            enviar(
                conn,
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                + f"Content-Length: {len(cuerpo)}\r\n\r\n".encode()
                + cuerpo,
            )
            return
        if req.startswith("GET /capture"):
            time.sleep(capture_espera_s)
            enviar(
                conn,
                respuesta_captura(
                    jpegs[n % 12], cabeceras=cabeceras_esp32(n, flush=True)
                ),
            )
            return
        enviar(conn, cabecera_http())
        i = 0
        while True:
            c = None if sin_cabeceras else cabeceras_esp32(i)
            try:
                enviar(conn, parte(jpegs[i % 12], cabeceras=c))
            except OSError:
                return
            i += 1
            time.sleep(pausa)

    return manejador


def manejador_droidcam(pausa=0.004):
    jpegs = [hacer_jpeg(100 + i, 96, 72) for i in range(12)]

    def manejador(conn, req, n):
        enviar(conn, cabecera_http())
        i = 0
        while True:
            try:
                enviar(conn, parte(jpegs[i % 12], con_cl=False))
            except OSError:
                return
            i += 1
            time.sleep(pausa)

    return manejador


def config_hacia(tmp_path, puerto_esp, puerto_dc, ancho=192, alto=108, **extra):
    """Config de prueba: ambas fuentes de red en 127.0.0.1 con los puertos dados."""
    t = RUTA_EJEMPLO.read_text()
    t = t.replace('ip = "192.168.43.100"', f'ip = "127.0.0.1"\npuerto = {puerto_esp}')
    t = t.replace(
        'ip = "192.168.43.1"\npuerto = 4747',
        f'ip = "127.0.0.1"\npuerto = {puerto_dc}',
    )
    t = t.replace("ancho = 1920", f"ancho = {ancho}").replace(
        "alto = 1080", f"alto = {alto}"
    )
    for k, v in extra.items():
        t = t.replace(k, v)
    ruta = tmp_path / "config.toml"
    ruta.write_text(t)
    return ruta


__all__ = [
    "ServidorFalso",
    "config_hacia",
    "esperar_cliente",
    "manejador_droidcam",
    "manejador_esp32",
]
