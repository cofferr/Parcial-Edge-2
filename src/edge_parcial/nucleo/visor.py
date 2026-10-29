"""Escritor de los últimos fotogramas para el visor del panel (solo lectura del núcleo).

Cada `1/fps_max` s toma `ultima_imagen` de cada trabajador, la reduce, la codifica a JPEG y la
publica con `os.replace` (el panel nunca ve un archivo a medias). Los JPEG pueden contener
rostros: viven en una carpeta ignorada por git y no se copian a ningún otro sitio.
"""

import os
import threading
from collections.abc import Callable, Mapping
from pathlib import Path

import cv2

ANCHO_MAX = 640
CALIDAD = 70


class EscritorVisor:
    def __init__(
        self,
        carpeta: Path | str,
        imagenes: Callable[[], Mapping[str, object]],
        fps_max: float = 5.0,
    ) -> None:
        self.carpeta = Path(carpeta)
        self.imagenes = imagenes
        self.periodo_s = 1.0 / fps_max
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._ultima_id: dict[str, int] = {}

    def iniciar(self) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self._hilo = threading.Thread(target=self._correr, name="visor", daemon=True)
        self._hilo.start()

    def detener(self) -> None:
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(2)

    def _correr(self) -> None:
        while not self._parar.wait(self.periodo_s):
            self.escribir_una_vez()

    def escribir_una_vez(self) -> None:
        for fuente, img in self.imagenes().items():
            if img is None or self._ultima_id.get(fuente) == id(img):
                continue  # sin fotograma nuevo: el archivo viejo envejece y el panel lo marca
            self._ultima_id[fuente] = id(img)
            try:
                self._publicar(fuente, img)
            except OSError, cv2.error:
                continue  # el visor es accesorio: nunca debe tumbar el núcleo

    def _publicar(self, fuente: str, img) -> None:
        alto, ancho = img.shape[:2]
        if ancho > ANCHO_MAX:
            img = cv2.resize(img, (ANCHO_MAX, round(alto * ANCHO_MAX / ancho)))
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, CALIDAD])
        if not ok:
            return
        self.carpeta.mkdir(parents=True, exist_ok=True)
        destino = self.carpeta / f"{fuente}.jpg"
        tmp = destino.with_name(f".{fuente}.{os.getpid()}.tmp")
        tmp.write_bytes(buf.tobytes())
        os.replace(tmp, destino)
