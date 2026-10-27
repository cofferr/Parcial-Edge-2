"""Lector de la cámara local (cv2.VideoCapture, backend AVFoundation explícito).

Definiciones para la cámara local (no hay ttx de red):
- t_request_ns: instante antes de read().
- t_ready_ns: inmediatamente después de que read() retorna (fotograma disponible).
- El e2e local es t_ready - t_request con la cámara ya abierta. La apertura no entra
  (se registra como evento `camara_abierta`) y tampoco la codificación JPEG.
- read() bloquea hasta el siguiente cuadro, así que incluye la espera por él (hasta un
  periodo de fotograma). La antigüedad del cuadro no se mide (DISENO.md §17).
- t_first_ns, t_last_ns, n_recv y header_bytes quedan vacíos.

La cámara se abre en el hilo principal (autorización de AVFoundation en macOS) y se
lee en el hilo lector, que SOLO lee y sella tiempos; la codificación va en otro hilo.
"""

import json
import queue
import time
from dataclasses import dataclass
from time import perf_counter_ns

import cv2
import numpy as np

from edge_parcial.acquisition.lector_red import SpecFuente, _LectorBase
from edge_parcial.config import Config, ParamsLector

ENDPOINT_LOCAL = "cv2.read"


class ErrorCamara(Exception):
    """La cámara no se pudo abrir."""


@dataclass
class ItemCodificar:
    fila: dict
    frame: np.ndarray


class CamaraCV2:
    """Envoltura de cv2.VideoCapture. No fuerza el FPS: queda como lo entregue la cámara."""

    def __init__(self, indice: int, ancho: int, alto: int) -> None:
        self.indice = indice
        self.ancho = ancho
        self.alto = alto
        self._cap: cv2.VideoCapture | None = None

    def abrir(self) -> dict:
        """Abre la cámara (llamar desde el hilo principal) y devuelve sus propiedades."""
        t0 = perf_counter_ns()
        cap = cv2.VideoCapture(self.indice, cv2.CAP_AVFOUNDATION)
        if not cap.isOpened():
            cap.release()
            raise ErrorCamara(
                f"No se pudo abrir la cámara {self.indice} (permiso de cámara de la "
                "terminal o índice incorrecto)"
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.ancho)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.alto)
        self._cap = cap
        fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
        return {
            "backend": cap.getBackendName(),
            "indice": self.indice,
            "ancho_solicitado": self.ancho,
            "alto_solicitado": self.alto,
            "ancho_reportado": cap.get(cv2.CAP_PROP_FRAME_WIDTH),
            "alto_reportado": cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
            "fps_reportado": cap.get(cv2.CAP_PROP_FPS),
            "fourcc": "".join(chr((fourcc >> (8 * i)) & 0xFF) for i in range(4)),
            "apertura_ns": perf_counter_ns() - t0,
        }

    def leer(self) -> tuple[bool, np.ndarray | None]:
        assert self._cap is not None, "la cámara no está abierta"
        return self._cap.read()

    def cerrar(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class CamaraSimulada:
    """Cámara falsa con la misma interfaz (abrir/leer/cerrar), para pruebas sin hardware.

    `intervalo_s` simula el periodo de fotograma (read() espera ese tiempo).
    `fallos`: índices de lectura que devuelven False; `fallar_desde`: desde esa lectura
    falla siempre.
    """

    def __init__(
        self,
        ancho: int = 192,
        alto: int = 108,
        intervalo_s: float = 0.0,
        fallos: set[int] | None = None,
        fallar_desde: int | None = None,
        fps_reportado: float = 30.0,
    ) -> None:
        self.ancho = ancho
        self.alto = alto
        self.intervalo_s = intervalo_s
        self.fallos = fallos or set()
        self.fallar_desde = fallar_desde
        self.fps_reportado = fps_reportado
        self.lecturas = 0
        self.abierta = False

    def abrir(self) -> dict:
        self.abierta = True
        return {
            "backend": "SIMULADA",
            "indice": 0,
            "ancho_solicitado": self.ancho,
            "alto_solicitado": self.alto,
            "ancho_reportado": float(self.ancho),
            "alto_reportado": float(self.alto),
            "fps_reportado": self.fps_reportado,
            "fourcc": "SIMU",
            "apertura_ns": 0,
        }

    def leer(self) -> tuple[bool, np.ndarray | None]:
        i = self.lecturas
        self.lecturas += 1
        if self.intervalo_s:
            time.sleep(self.intervalo_s)
        if i in self.fallos or (
            self.fallar_desde is not None and i >= self.fallar_desde
        ):
            return False, None
        rng = np.random.default_rng(i)
        return True, rng.integers(0, 256, (self.alto, self.ancho, 3), dtype=np.uint8)

    def cerrar(self) -> None:
        self.abierta = False


class LectorLocal(_LectorBase):
    """Hilo lector de la cámara local: solo read() y marcas de tiempo."""

    def __init__(
        self,
        camara,
        propiedades: dict,
        params: ParamsLector,
        ancho: int,
        alto: int,
        run_id: str,
        condition: str,
        cola: queue.Queue,
        sink_fila,
        sink_evento,
        n_total: int | None = None,
    ) -> None:
        spec = SpecFuente("local", "", 0, ENDPOINT_LOCAL)
        super().__init__(
            spec, params, run_id, condition, None, cola, sink_fila, sink_evento, n_total
        )
        self.camara = camara
        self.propiedades = propiedades
        self.solicitada = (ancho, alto)
        self.resumen.resolucion_solicitada = self.solicitada
        self._primer_fotograma = True

    def run(self) -> None:
        self._evento(
            "camara_abierta", detalle=json.dumps(self.propiedades, sort_keys=True)
        )
        fallos = 0
        while not self._parar.is_set() and not self._completo():
            t_req = perf_counter_ns()
            ok, frame = self.camara.leer()
            t_ready = perf_counter_ns()  # inmediatamente tras read()
            if not ok or frame is None:
                fila = self._fila_base(0, t_req)
                fila["error"] = "read() devolvió False"
                self.resumen.sumar(fotogramas=1, errores=1)
                self.sink_fila(fila)
                fallos += 1
                if fallos >= self.params.intentos_max:
                    self.resumen.abandonada = True
                    self._evento(
                        "abandono", detalle=f"{fallos} lecturas fallidas seguidas"
                    )
                    return
                continue
            fallos = 0
            alto, ancho = frame.shape[:2]
            if self._primer_fotograma:
                self._primer_fotograma = False
                self._verificar_resolucion(ancho, alto)
            fila = self._fila_base(0, t_req)
            fila.update(
                t_ready_ns=t_ready,
                raw_bytes=frame.nbytes,
                width=ancho,
                height=alto,
            )
            self.resumen.sumar(fotogramas=1)
            try:
                self.cola.put_nowait(ItemCodificar(fila, frame))
            except queue.Full:
                fila["descartado"] = 1
                self.resumen.sumar(descartes=1)
                self.sink_fila(fila)

    def _verificar_resolucion(self, ancho: int, alto: int) -> None:
        self.resumen.resolucion_real = (ancho, alto)
        if (ancho, alto) != self.solicitada:
            motivo = (
                f"resolución real {ancho}x{alto} distinta de la solicitada "
                f"{self.solicitada[0]}x{self.solicitada[1]}"
            )
            self.resumen.motivos_extra.append(motivo)
            self._evento("resolucion_inesperada", detalle=motivo)


def crear_camara(cfg: Config) -> CamaraCV2:
    return CamaraCV2(cfg.local.indice_camara, cfg.local.ancho, cfg.local.alto)
