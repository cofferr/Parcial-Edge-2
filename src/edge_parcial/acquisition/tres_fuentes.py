"""Tarea 1.1: tres fuentes con cv2.VideoCapture literal y tres ventanas.

El hilo principal dibuja las tres ventanas (exigencia de macOS); un hilo lector por
fuente hace `cap.read()` y deja el último fotograma. Cierre con "q" o cerrando una
ventana, con liberación ordenada de capturas y ventanas.

Recuerda: la ESP32-CAM admite UN solo cliente; no abras /stream en otro lado.
"""

import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from edge_parcial.acquisition.pantalla import TECLA_Q, Pantalla
from edge_parcial.config import Config

TAM_PLACEHOLDER = (360, 640)  # alto, ancho


@dataclass(frozen=True)
class FuenteVideo:
    nombre: str
    origen: int | str  # índice de cámara o URL
    abrir_en_principal: bool = False  # la cámara local se abre en el hilo principal


def fuentes_desde_config(
    cfg: Config, incluir: tuple[str, ...] = ("local", "esp32", "droidcam")
):
    todas = {
        "local": FuenteVideo("local", cfg.local.indice_camara, abrir_en_principal=True),
        "esp32": FuenteVideo(
            "esp32", f"http://{cfg.esp32.ip}:{cfg.esp32.puerto}/stream"
        ),
        "droidcam": FuenteVideo(
            "droidcam", f"http://{cfg.droidcam.ip}:{cfg.droidcam.puerto}/video"
        ),
    }
    return [todas[n] for n in incluir]


@dataclass
class Estado:
    frame: np.ndarray | None = None
    n: int = 0  # fotogramas recibidos
    fps: float = 0.0
    error: str | None = None
    abierta: bool = False
    _marcas: list = field(default_factory=list)


class LectorCV2(threading.Thread):
    """Lee con cap.read() y publica el último fotograma."""

    def __init__(
        self, fuente: FuenteVideo, fabrica, detener: threading.Event, cap=None
    ):
        super().__init__(name=f"cv2-{fuente.nombre}", daemon=True)
        self.fuente = fuente
        self.fabrica = fabrica
        self.detener = detener
        self.estado = Estado()
        self._lock = threading.Lock()
        self._cap = cap

    def instantanea(self) -> Estado:
        with self._lock:
            e = self.estado
            return Estado(e.frame, e.n, e.fps, e.error, e.abierta)

    def run(self) -> None:
        cap = self._cap
        try:
            if cap is None:
                cap = self.fabrica(self.fuente.origen)
            if not cap.isOpened():
                with self._lock:
                    self.estado.error = "no se pudo abrir la fuente"
                return
            with self._lock:
                self.estado.abierta = True
            fallos = 0
            while not self.detener.is_set():
                ok, frame = cap.read()
                ahora = time.monotonic()
                with self._lock:
                    if not ok or frame is None:
                        fallos += 1
                        if fallos >= 5:
                            self.estado.error = "sin señal (read() falló)"
                            self.estado.frame = None
                        time.sleep(0.02)
                        continue
                    fallos = 0
                    self.estado.error = None
                    self.estado.frame = frame
                    self.estado.n += 1
                    marcas = self.estado._marcas
                    marcas.append(ahora)
                    while marcas and ahora - marcas[0] > 1.0:
                        marcas.pop(0)
                    self.estado.fps = (
                        len(marcas) / max(ahora - marcas[0], 1e-3)
                        if len(marcas) > 1
                        else 0.0
                    )
        except Exception as e:  # noqa: BLE001 - la fuente cae, las demás siguen
            with self._lock:
                self.estado.error = f"{type(e).__name__}: {e}"
        finally:
            if cap is not None:
                cap.release()


def _con_texto(frame: np.ndarray | None, lineas: list[str]) -> np.ndarray:
    img = (
        np.zeros((*TAM_PLACEHOLDER, 3), np.uint8)
        if frame is None
        else (
            frame if frame.ndim == 3 else cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        ).copy()
    )
    for i, t in enumerate(lineas):
        y = 24 + 24 * i
        cv2.putText(
            img, t, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA
        )
        cv2.putText(
            img, t, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1, cv2.LINE_AA
        )
    return img


class VisorTresFuentes:
    def __init__(
        self, fuentes, pantalla: Pantalla, fabrica=cv2.VideoCapture, espera_ms: int = 15
    ):
        self.fuentes = fuentes
        self.pantalla = pantalla
        self.fabrica = fabrica
        self.espera_ms = espera_ms
        self.detener = threading.Event()
        self.lectores: list[LectorCV2] = []

    def ejecutar(self, max_iteraciones: int | None = None) -> dict:
        """Bucle principal (hilo principal). Devuelve un resumen al cerrar."""
        motivo = "límite de iteraciones"
        try:
            for f in self.fuentes:
                cap = self.fabrica(f.origen) if f.abrir_en_principal else None
                lector = LectorCV2(f, self.fabrica, self.detener, cap)
                self.lectores.append(lector)
                lector.start()
            iteracion = 0
            while max_iteraciones is None or iteracion < max_iteraciones:
                iteracion += 1
                for lector in self.lectores:
                    e = lector.instantanea()
                    if e.error:
                        img = _con_texto(None, [lector.fuente.nombre, e.error.upper()])
                    elif e.frame is None:
                        img = _con_texto(None, [lector.fuente.nombre, "conectando..."])
                    else:
                        h, w = e.frame.shape[:2]
                        img = _con_texto(
                            e.frame, [lector.fuente.nombre, f"{w}x{h}  {e.fps:.1f} FPS"]
                        )
                    self.pantalla.mostrar(lector.fuente.nombre, img)
                if self.pantalla.tecla(self.espera_ms) in (TECLA_Q, ord("Q")):
                    motivo = "tecla q"
                    break
                if any(not self.pantalla.visible(f.nombre) for f in self.fuentes):
                    motivo = "ventana cerrada"
                    break
        finally:
            self.detener.set()
            for lector in self.lectores:
                lector.join(3)
            self.pantalla.cerrar()
        return {
            "motivo_cierre": motivo,
            "fuentes": {
                lector.fuente.nombre: {
                    "fotogramas": lector.estado.n,
                    "error": lector.estado.error,
                    "abierta": lector.estado.abierta,
                }
                for lector in self.lectores
            },
        }
