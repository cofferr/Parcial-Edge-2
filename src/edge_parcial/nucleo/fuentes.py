"""Capa device del núcleo: las tres fuentes entregan `FotogramaEdge` decodificados.

Reutiliza los lectores de la Parte 1 (sockets propios para ESP32 y DroidCam; `read()` de
AVFoundation para la local) y sustituye el consumidor: en vez de escribir filas, el
decodificador entrega la imagen al edge. `EntradaSimulada` sirve para pruebas y ensayos.
"""

import queue
import threading
import time
from collections import deque
from time import perf_counter_ns

import cv2
import numpy as np

from edge_parcial.acquisition.decodificador import Decodificador
from edge_parcial.acquisition.lector_local import LectorLocal, crear_camara
from edge_parcial.acquisition.lector_red import (
    LectorStream,
    spec_droidcam,
    spec_esp32_stream,
)
from edge_parcial.config import Config
from edge_parcial.nucleo.modelo import FotogramaEdge

TIPOS_ERROR = ("corte", "reintento", "abandono", "resolucion_inesperada")


def fotograma_desde_fila(fila: dict, img: np.ndarray) -> FotogramaEdge:
    return FotogramaEdge(
        source=fila["source"],
        seq=fila["seq"],
        t_ready_ns=fila["t_ready_ns"],
        img=img,
        t_request_ns=fila["t_request_ns"],
        t_first_ns=fila["t_first_ns"],
        capture_us=fila["capture_us"],
        jpeg_us=fila["jpeg_us"],
        flush_us=fila["flush_us"],
    )


class DecodificadorEdge(Decodificador):
    """`imdecode` en su propio hilo (como en la Parte 1) y entrega la imagen al edge."""

    def __init__(self, cola: queue.Queue, sink_frame, nombre: str) -> None:
        super().__init__(cola, lambda fila: None, nombre)
        self.sink_frame = sink_frame

    def _procesar(self, item) -> None:
        fila = item.fila
        if not item.decodificar:
            self.fallidos += 1
            return
        datos = np.frombuffer(item.payload, dtype=np.uint8)
        t_ini = perf_counter_ns()
        img = cv2.imdecode(datos, self.flags)
        t_ready = perf_counter_ns()  # inmediatamente tras imdecode
        if img is None:
            self.fallidos += 1
            return
        fila["t_decode_ini_ns"], fila["t_ready_ns"] = t_ini, t_ready
        self.decodificados += 1
        self.sink_frame(fotograma_desde_fila(fila, img))


class _Errores:
    """Últimos eventos de error de una fuente (para `errores_recientes`)."""

    def __init__(self, maximo: int = 5) -> None:
        self._d: deque[str] = deque(maxlen=maximo)

    def evento(self, e: dict) -> None:
        if e["tipo"] in TIPOS_ERROR:
            self._d.append(f"{e['tipo']}: {e['detalle'] or ''}".strip())

    def lista(self) -> list[str]:
        return list(self._d)


class EntradaRed:
    """ESP32-CAM (/stream) o DroidCam (/video): LectorStream + decodificador."""

    def __init__(self, cfg: Config, nombre: str, run_id: str = "nucleo") -> None:
        self.nombre = nombre
        self.cfg = cfg
        self.run_id = run_id
        self._errores = _Errores()
        self._lector: LectorStream | None = None
        self._dec: DecodificadorEdge | None = None

    def abrir(self) -> None:
        """Sin trabajo en el hilo principal: los sockets se abren en el hilo lector."""

    def iniciar(self, sink) -> None:
        spec = spec_esp32_stream(self.cfg) if self.nombre == "esp32" else spec_droidcam(self.cfg)  # fmt: skip
        cola = queue.Queue(maxsize=self.cfg.lector.cola_max)
        self._dec = DecodificadorEdge(cola, sink, f"decodificador-{self.nombre}")
        self._lector = LectorStream(
            spec, self.cfg.lector, self.run_id, "nucleo", None, cola,
            lambda fila: None, self._errores.evento,
        )  # fmt: skip
        self._dec.start()
        self._lector.start()

    def detener(self) -> None:
        if self._lector is not None:
            self._lector.detener()
            self._lector.join(5)
        if self._dec is not None:
            self._dec.cerrar(5)

    def viva(self) -> bool:
        return (
            self._lector is not None
            and self._lector.is_alive()
            and not self._lector.resumen.abandonada
        )

    def errores(self) -> list[str]:
        return self._errores.lista()


class _AdaptadorCola:
    """Cola falsa para LectorLocal: convierte cada fotograma y lo entrega al edge."""

    def __init__(self, sink) -> None:
        self.sink = sink

    def put_nowait(self, item) -> None:
        self.sink(fotograma_desde_fila(item.fila, item.frame))


class EntradaLocal:
    """Cámara local (AVFoundation). Se abre en el hilo principal y se lee en el lector."""

    nombre = "local"

    def __init__(self, cfg: Config, camara_factory=crear_camara, run_id: str = "nucleo") -> None:  # fmt: skip
        self.cfg = cfg
        self.camara_factory = camara_factory
        self.run_id = run_id
        self._errores = _Errores()
        self._camara = None
        self._props: dict = {}
        self._lector: LectorLocal | None = None

    def abrir(self) -> None:
        self._camara = self.camara_factory(self.cfg)
        self._props = self._camara.abrir()

    def iniciar(self, sink) -> None:
        self._lector = LectorLocal(
            self._camara, self._props, self.cfg.lector, self.cfg.local.ancho,
            self.cfg.local.alto, self.run_id, "nucleo", _AdaptadorCola(sink),
            lambda fila: None, self._errores.evento, None,
        )  # fmt: skip
        self._lector.start()

    def detener(self) -> None:
        if self._lector is not None:
            self._lector.detener()
            self._lector.join(5)
        if self._camara is not None:
            self._camara.cerrar()

    def viva(self) -> bool:
        return (
            self._lector is not None
            and self._lector.is_alive()
            and not self._lector.resumen.abandonada
        )

    def errores(self) -> list[str]:
        return self._errores.lista()


class EntradaSimulada:
    """Fuente sintética: `generador(t_s)` devuelve la imagen a `fps`; opcionalmente cae."""

    def __init__(
        self,
        nombre: str,
        generador,
        fps: float = 20.0,
        caida_desde_s: float | None = None,
        retardo_device_s: float = 0.0,
    ) -> None:
        self.nombre = nombre
        self.generador = generador
        self.fps = fps
        self.caida_desde_s = caida_desde_s
        self.retardo_device_s = retardo_device_s
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self.emitidos = 0

    def abrir(self) -> None:
        pass

    def iniciar(self, sink) -> None:
        self._t_ini = time.monotonic()
        self._hilo = threading.Thread(
            target=self._bucle, args=(sink,), name=f"sim-{self.nombre}", daemon=True
        )
        self._hilo.start()

    def _bucle(self, sink) -> None:
        periodo = 1.0 / self.fps
        seq = 0
        while not self._parar.wait(periodo):
            t_s = time.monotonic() - self._t_ini
            if self.caida_desde_s is not None and t_s >= self.caida_desde_s:
                continue  # fuente caída: no entrega nada
            t_first = perf_counter_ns()
            if self.retardo_device_s:
                time.sleep(self.retardo_device_s)
            img = self.generador(t_s)
            sink(
                FotogramaEdge(
                    self.nombre, seq, perf_counter_ns(), img,
                    t_request_ns=t_first, t_first_ns=t_first,
                )
            )  # fmt: skip
            seq += 1
            self.emitidos += 1

    def detener(self) -> None:
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(2)

    def viva(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive()

    def errores(self) -> list[str]:
        return []


def construir_entradas(
    cfg: Config, fuentes=("esp32", "droidcam", "local"), camara_factory=crear_camara
) -> dict:
    """Las entradas reales por nombre. La local debe abrirse en el hilo principal."""
    return {
        f: (EntradaLocal(cfg, camara_factory) if f == "local" else EntradaRed(cfg, f))
        for f in fuentes
    }
