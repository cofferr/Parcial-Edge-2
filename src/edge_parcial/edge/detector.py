"""Detector de movimiento por fuente y voto por ventana (docs/DISENO.md §23).

Por fotograma: gris -> reducción a tamaño común -> gaussiano; absdiff contra el último
fotograma con edad >= `edad_ref_ms` (así el intervalo temporal es comparable entre la
ESP32 de ~3 fps y las demás); hay movimiento si la fracción de píxeles con diferencia
> `t_pix` supera `t_area`. Se rechazan los cambios globales (`cambio_global`) y se marca
`tapada` a la fuente oscura durante >= `tapada_s`.
"""

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field

import cv2
import numpy as np

from edge_parcial import filtro

MS_A_NS = 1_000_000
S_A_NS = 1_000_000_000

BANDERA_SIN_DATOS = "sin_datos"
BANDERA_TAPADA = "tapada"
BANDERA_MOVIMIENTO = "movimiento"
BANDERA_CAMBIO_GLOBAL = "cambio_global"
BANDERA_QUIETO = "quieto"


@dataclass(frozen=True)
class ParamsDetector:
    t_pix: float
    t_area: float
    umbral_voto: float = 0.3
    tam: tuple[int, int] = filtro.TAM_COMUN  # (ancho, alto)
    umbral_global: float = 0.6  # fracción cambiada que se considera cambio global
    salto_luminancia: float = 40.0  # variación brusca de la luminancia media (0-255)
    umbral_oscuro: float = 25.0  # luminancia media bajo la cual la fuente "está oscura"
    tapada_s: float = 1.0
    edad_ref_ms: float = 200.0


@dataclass(frozen=True)
class ResultadoFotograma:
    t_ns: int
    evaluado: bool  # False si aún no hay referencia con la edad pedida
    fraccion: float  # NaN si no se evaluó
    luminancia: float
    movimiento: bool
    cambio_global: bool
    tapada: bool


@dataclass
class DetectorMovimiento:
    """Detector con estado de una fuente. Los fotogramas llegan en orden de `t_ns`."""

    params: ParamsDetector
    _historial: deque = field(default_factory=deque, repr=False)  # (t_ns, gris, lum)
    _oscuro_desde_ns: int | None = field(default=None, repr=False)

    def procesar(self, img: np.ndarray, t_ns: int) -> ResultadoFotograma:
        return self.procesar_preparado(filtro.preparar(img, self.params.tam), t_ns)

    def procesar_preparado(self, gris: np.ndarray, t_ns: int) -> ResultadoFotograma:
        """Igual que `procesar` con el fotograma ya preparado (gris, reducido, suavizado)."""
        p = self.params
        lum = float(gris.mean())
        ref = self._referencia(t_ns)
        self._historial.append((t_ns, gris, lum))
        tapada = self._actualizar_oscuridad(lum, t_ns)
        if ref is None:
            return ResultadoFotograma(t_ns, False, math.nan, lum, False, False, tapada)
        _, gris_ref, lum_ref = ref
        fraccion = float(np.mean(cv2.absdiff(gris, gris_ref) > p.t_pix))
        global_ = fraccion > p.umbral_global or abs(lum - lum_ref) > p.salto_luminancia
        movimiento = fraccion > p.t_area and not global_ and not tapada
        return ResultadoFotograma(
            t_ns, True, fraccion, lum, movimiento, global_, tapada
        )

    def _referencia(self, t_ns: int):
        """Último fotograma con edad >= edad_ref_ms; descarta los anteriores a ese."""
        limite = t_ns - int(self.params.edad_ref_ms * MS_A_NS)
        h = self._historial
        while len(h) >= 2 and h[1][0] <= limite:
            h.popleft()
        return h[0] if h and h[0][0] <= limite else None

    def _actualizar_oscuridad(self, lum: float, t_ns: int) -> bool:
        if lum >= self.params.umbral_oscuro:
            self._oscuro_desde_ns = None
            return False
        if self._oscuro_desde_ns is None:
            self._oscuro_desde_ns = t_ns
        return t_ns - self._oscuro_desde_ns >= int(self.params.tapada_s * S_A_NS)


def votar(
    resultados: Sequence[ResultadoFotograma], umbral_voto: float
) -> tuple[bool, str, float]:
    """Voto de una ventana: (voto, bandera, fracción de fotogramas con movimiento).

    Sin fotogramas evaluados el voto es False con `sin_datos`; nunca se arrastra el
    voto de la ventana anterior. La bandera usa la precedencia de DISENO §23.
    """
    evaluados = [r for r in resultados if r.evaluado]
    if not evaluados:
        return False, BANDERA_SIN_DATOS, math.nan
    frac = sum(r.movimiento for r in evaluados) / len(evaluados)
    if resultados[-1].tapada:
        return False, BANDERA_TAPADA, frac
    if frac >= umbral_voto:
        return True, BANDERA_MOVIMIENTO, frac
    if any(r.cambio_global for r in evaluados):
        return False, BANDERA_CAMBIO_GLOBAL, frac
    return False, BANDERA_QUIETO, frac
