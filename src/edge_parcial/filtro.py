"""Filtro de transmisión por diferencia con el ÚLTIMO fotograma transmitido (Tarea 1.6).

Preprocesado común a todas las fuentes: gris -> reducción a tamaño fijo -> suavizado
gaussiano. Un fotograma se transmite si la fracción de píxeles cuya diferencia absoluta
con la referencia supera `t_pix` es mayor que `t_area`. La referencia es el último
fotograma TRANSMITIDO (no el anterior), así que un cambio lento acaba superando el
umbral. El primer fotograma siempre se transmite.

`f` = fracción transmitida (por fotogramas o por bytes); el ahorro es (1 - f).
"""

import itertools
import math

import cv2
import numpy as np

TAM_COMUN = (160, 120)  # ancho, alto
KERNEL_SUAVIZADO = 5


def preparar(img: np.ndarray, tam: tuple[int, int] = TAM_COMUN) -> np.ndarray:
    """Gris + reducción a tamaño común + suavizado. Devuelve uint8 (alto, ancho)."""
    gris = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    chica = cv2.resize(gris, tam, interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(chica, (KERNEL_SUAVIZADO, KERNEL_SUAVIZADO), 0)


def fraccion_cambiada(a: np.ndarray, b: np.ndarray, t_pix: float) -> float:
    return float(np.mean(cv2.absdiff(a, b) > t_pix))


class FiltroDiferencia:
    def __init__(self, t_pix: float, t_area: float) -> None:
        self.t_pix = t_pix
        self.t_area = t_area
        self.referencia: np.ndarray | None = None

    def procesar(self, gris: np.ndarray) -> bool:
        """True si el fotograma (ya preparado) se transmite."""
        if self.referencia is None or (
            fraccion_cambiada(gris, self.referencia, self.t_pix) > self.t_area
        ):
            self.referencia = gris
            return True
        return False


def simular(grises: list[np.ndarray], t_pix: float, t_area: float) -> np.ndarray:
    """Máscara booleana de transmisión para una secuencia de fotogramas preparados."""
    filtro = FiltroDiferencia(t_pix, t_area)
    return np.array([filtro.procesar(g) for g in grises], dtype=bool)


def calibrar_t_pix(
    grises_estaticos: list[np.ndarray], percentil: float = 99.9
) -> float:
    """T_pix = percentil del ruido |f[i] - f[i-1]| con la escena estática, redondeado arriba.

    Mínimo 1: una diferencia 0 no distingue ruido de cambio.
    """
    if len(grises_estaticos) < 2:
        raise ValueError("Se necesitan al menos 2 fotogramas estáticos para calibrar")
    difs = np.concatenate(
        [cv2.absdiff(b, a).ravel() for a, b in itertools.pairwise(grises_estaticos)]
    )
    return float(max(1, math.ceil(np.percentile(difs, percentil))))


def candidatos_t_area(n: int = 60, minimo: float = 1e-4, maximo: float = 0.5):
    """Rejilla logarítmica de umbrales de área (fracción de píxeles)."""
    return [float(x) for x in np.geomspace(minimo, maximo, n)]


def barrido_t_area(
    grises_estaticos: list[np.ndarray], t_pix: float, candidatos: list[float]
) -> list[tuple[float, float]]:
    """(t_area, fracción de fotogramas estáticos transmitidos), sin contar el primero."""
    salida = []
    for t_area in candidatos:
        m = simular(grises_estaticos, t_pix, t_area)
        resto = m[1:]
        salida.append((t_area, float(resto.mean()) if len(resto) else 0.0))
    return salida


def elegir_t_area(
    grises_estaticos: list[np.ndarray],
    t_pix: float,
    max_estaticos_tx: float = 0.01,
    candidatos: list[float] | None = None,
) -> tuple[float, list[tuple[float, float]]]:
    """El menor T_area con <= `max_estaticos_tx` de estáticos transmitidos (más sensible).

    Devuelve (t_area, barrido). Si ninguno cumple, ValueError (no se inventa un umbral).
    """
    barrido = barrido_t_area(grises_estaticos, t_pix, candidatos or candidatos_t_area())
    for t_area, frac in barrido:
        if frac <= max_estaticos_tx:
            return t_area, barrido
    raise ValueError(
        f"Ningún T_area deja <= {100 * max_estaticos_tx:.1f} % de estáticos transmitidos"
    )
