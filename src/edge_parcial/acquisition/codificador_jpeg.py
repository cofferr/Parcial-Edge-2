"""Hilo codificador: JPEG de referencia de la cámara local (tamaño y costo).

El tiempo se mide con perf_counter_ns alrededor de cv2.imencode ÚNICAMENTE
(t_encode_ini_ns / t_encode_fin_ns). Es solo referencia de tamaño y costo: no entra
en el e2e de la cámara local. La validación SOI/EOI se hace fuera de esa medición.
"""

import queue
import threading
from time import perf_counter_ns

import cv2

from edge_parcial.acquisition.lector_local import ItemCodificar
from edge_parcial.acquisition.mjpeg import EOI, SOI


class CodificadorJPEG(threading.Thread):
    def __init__(
        self,
        cola: queue.Queue,
        sink_fila,
        calidad: int = 50,
        nombre: str = "codificador-local",
    ) -> None:
        super().__init__(name=nombre, daemon=True)
        self.cola = cola
        self.sink_fila = sink_fila
        self.calidad = calidad
        self.codificados = 0
        self.fallidos = 0

    def cerrar(self, espera: float = 10.0) -> None:
        """Termina tras procesar lo que ya está en la cola."""
        self.cola.put(None)
        self.join(espera)

    def run(self) -> None:
        while (item := self.cola.get()) is not None:
            self._procesar(item)

    def _procesar(self, item: ItemCodificar) -> None:
        fila = item.fila
        t_ini = perf_counter_ns()
        ok, buf = cv2.imencode(
            ".jpg", item.frame, [cv2.IMWRITE_JPEG_QUALITY, self.calidad]
        )
        t_fin = perf_counter_ns()  # inmediatamente tras imencode
        fila["t_encode_ini_ns"] = t_ini
        fila["t_encode_fin_ns"] = t_fin
        if not ok:
            fila["error"] = "; ".join(filter(None, [fila["error"], "imencode falló"]))
            self.fallidos += 1
        else:
            fila["payload_bytes"] = int(buf.size)
            fila["jpeg_valid"] = int(
                buf.size >= 4 and buf[:2].tobytes() == SOI and buf[-2:].tobytes() == EOI
            )
            self.codificados += 1
        self.sink_fila(fila)
