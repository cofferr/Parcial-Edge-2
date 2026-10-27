"""Utilidades de prueba: JPEG reales, partes MJPEG y un servidor TCP falso."""

import random
import socket
import threading
import time

import cv2
import numpy as np


def hacer_jpeg(
    semilla: int = 0, ancho: int = 64, alto: int = 48, calidad: int = 50
) -> bytes:
    """JPEG real, de contenido distinto por semilla (tamaño variable)."""
    rng = np.random.default_rng(semilla)
    img = rng.integers(0, 256, (alto, ancho), dtype=np.uint8)
    img[: alto // 2] = (img[: alto // 2] // (1 + semilla % 7)).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, calidad])
    assert ok
    return buf.tobytes()


def jpeg_con_app_falso(jpeg: bytes) -> bytes:
    """Inserta un segmento APP1 con un FFD9 dentro (como una miniatura incrustada)."""
    relleno = b"Exif\x00\x00" + b"\x01\x02\xff\xd9\x03\x04"
    seg = b"\xff\xe1" + (len(relleno) + 2).to_bytes(2, "big") + relleno
    return jpeg[:2] + seg + jpeg[2:]


def cabecera_http(boundary: str = "frame", extra: str = "") -> bytes:
    return (
        "HTTP/1.1 200 OK\r\n"
        f"Content-Type: multipart/x-mixed-replace; boundary={boundary}\r\n"
        f"{extra}\r\n"
    ).encode()


def parte(
    jpeg: bytes,
    boundary: str = "frame",
    con_cl: bool = True,
    cabeceras: dict | None = None,
) -> bytes:
    """Una parte multipart: delimitador + cabeceras + JPEG + CRLF."""
    h = f"--{boundary}\r\nContent-Type: image/jpeg\r\n"
    if con_cl:
        h += f"Content-Length: {len(jpeg)}\r\n"
    for k, v in (cabeceras or {}).items():
        h += f"{k}: {v}\r\n"
    return h.encode() + b"\r\n" + jpeg + b"\r\n"


def cabeceras_esp32(i: int = 0, flush: bool = False) -> dict:
    d = {"X-Capture-Us": 1000 + i, "X-Jpeg-Us": 2000 + i, "X-Rssi-Dbm": -50 - i % 5}
    if flush:
        d["X-Flush-Us"] = 30 + i
    return d


def respuesta_captura(
    jpeg: bytes, con_cl: bool = True, cabeceras: dict | None = None
) -> bytes:
    h = "HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nConnection: close\r\n"
    if con_cl:
        h += f"Content-Length: {len(jpeg)}\r\n"
    for k, v in (cabeceras or {}).items():
        h += f"{k}: {v}\r\n"
    return h.encode() + b"\r\n" + jpeg


def trozos_aleatorios(datos: bytes, semilla: int, maximo: int = 200) -> list[bytes]:
    rng = random.Random(semilla)
    salida, i = [], 0
    while i < len(datos):
        n = rng.randint(1, maximo)
        salida.append(datos[i : i + n])
        i += n
    return salida


def enviar(
    conn: socket.socket, datos: bytes, trozo: int = 0, pausa: float = 0.0
) -> None:
    """Envía datos, opcionalmente en trozos de tamaño fijo con pausa entre ellos."""
    if not trozo:
        conn.sendall(datos)
        return
    for i in range(0, len(datos), trozo):
        conn.sendall(datos[i : i + trozo])
        if pausa:
            time.sleep(pausa)


class ServidorFalso:
    """Servidor TCP local. `manejador(conn, peticion, n_conexion)` guioniza cada conexión."""

    def __init__(self, manejador):
        self.manejador = manejador
        self.peticiones: list[str] = []
        self._lock = threading.Lock()
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self.puerto = self._sock.getsockname()[1]
        self._parar = False
        self._hilo = threading.Thread(target=self._aceptar, daemon=True)

    def _aceptar(self):
        while not self._parar:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with self._lock:
                n = len(self.peticiones)
                self.peticiones.append("")
            threading.Thread(target=self._atender, args=(conn, n), daemon=True).start()

    def _atender(self, conn, n):
        try:
            datos = b""
            conn.settimeout(5)
            while b"\r\n\r\n" not in datos:
                trozo = conn.recv(4096)
                if not trozo:
                    return
                datos += trozo
            peticion = datos.decode("latin-1")
            self.peticiones[n] = peticion
            self.manejador(conn, peticion, n)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def __enter__(self):
        self._hilo.start()
        return self

    def __exit__(self, *args):
        self._parar = True
        self._sock.close()
