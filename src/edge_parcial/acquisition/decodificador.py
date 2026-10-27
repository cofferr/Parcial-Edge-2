"""Hilo decodificador: cv2.imdecode fuera del hilo lector.

t_decode_ini_ns = justo antes de imdecode; t_ready_ns = justo después.
tproc_host se reporta separado (ver docs/DISENO.md):
  espera en cola = t_decode_ini - t_last;  decodificación = t_ready - t_decode_ini.
Solo la decodificación entra a la fórmula.
"""

import queue
import threading
from time import perf_counter_ns

import cv2
import numpy as np

from edge_parcial.acquisition.lector_red import ItemDecodificar


class Decodificador(threading.Thread):
    def __init__(
        self,
        cola: queue.Queue,
        sink_fila,
        nombre: str = "decodificador",
        flags: int = cv2.IMREAD_COLOR,
    ) -> None:
        super().__init__(name=nombre, daemon=True)
        self.cola = cola
        self.sink_fila = sink_fila
        self.flags = flags
        self.decodificados = 0
        self.fallidos = 0

    def cerrar(self, espera: float = 10.0) -> None:
        """Termina tras procesar lo que ya está en la cola."""
        self.cola.put(None)
        self.join(espera)

    def run(self) -> None:
        while True:
            item = self.cola.get()
            if item is None:
                return
            self._procesar(item)

    def _procesar(self, item: ItemDecodificar) -> None:
        fila = item.fila
        if not item.decodificar:
            # JPEG ya marcado inválido por el lector (SOI/EOI/estructura): no se decodifica.
            fila["error"] = fila["error"] or "JPEG inválido: no se decodificó"
            self.fallidos += 1
            self.sink_fila(fila)
            return
        datos = np.frombuffer(item.payload, dtype=np.uint8)
        t_ini = perf_counter_ns()
        img = cv2.imdecode(datos, self.flags)
        t_ready = perf_counter_ns()  # inmediatamente tras imdecode
        fila["t_decode_ini_ns"] = t_ini
        if img is None:
            fila["error"] = "; ".join(
                filter(None, [fila["error"], "imdecode devolvió None"])
            )
            self.fallidos += 1
        else:
            fila["t_ready_ns"] = t_ready
            fila["height"], fila["width"] = img.shape[:2]
            self.decodificados += 1
        self.sink_fila(fila)
