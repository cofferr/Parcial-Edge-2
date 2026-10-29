"""Foto de evidencia: un cuadro JPEG tomado de un flujo MJPEG (DroidCam) o de una imagen fija."""

import urllib.request
from pathlib import Path

MAX_BYTES = 5_000_000


def extraer_frame(url: str, timeout: float = 15) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        if url.lower().endswith(".jpg"):
            return r.read()
        buf = b""
        while len(buf) < MAX_BYTES:
            trozo = r.read(4096)
            if not trozo:
                break
            buf += trozo
            ini = buf.find(b"\xff\xd8")  # inicio de JPEG
            if ini != -1:
                fin = buf.find(b"\xff\xd9", ini + 2)  # fin de JPEG
                if fin != -1:
                    return buf[ini : fin + 2]
    raise RuntimeError("no se pudo extraer un cuadro del flujo")


def guardar_foto(url: str, ruta: Path) -> int:
    datos = extraer_frame(url)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(datos)
    return len(datos)
