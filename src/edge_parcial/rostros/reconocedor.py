"""Reconocedores de rostros detrás de una interfaz común.

`ReconocedorDlib` usa face_recognition (importado de forma diferida); `ReconocedorFalso`
no necesita dlib y sirve para pruebas y como respaldo si dlib no importa.
"""

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

log = logging.getLogger("edge_parcial.rostros")

DESCONOCIDO = "desconocido"
EXTENSIONES_VALIDAS = (".jpg", ".jpeg", ".png")
TOLERANCIA = 0.6  # distancia máxima para considerar un rostro conocido

# dlib/face_recognition no es thread-safe: se serializan todas las llamadas.
LOCK_DLIB = threading.Lock()


@dataclass(frozen=True)
class Deteccion:
    identidad: str
    distancia: float | None  # None si no hay rostros conocidos con que comparar
    caja: tuple[
        int, int, int, int
    ]  # (top, right, bottom, left) en píxeles de la imagen recibida


class Reconocedor(Protocol):
    nombre: str

    def reconocer(self, rgb: np.ndarray) -> list[Deteccion]:
        """Detecta e identifica rostros en una imagen RGB (ya reducida)."""
        ...


class ReconocedorFalso:
    """Devuelve siempre las detecciones configuradas (por defecto, ninguna)."""

    nombre = "falso"

    def __init__(self, detecciones: list[Deteccion] | None = None) -> None:
        self.detecciones = list(detecciones or [])
        self.ultima_forma: tuple[int, ...] | None = None

    def reconocer(self, rgb: np.ndarray) -> list[Deteccion]:
        self.ultima_forma = rgb.shape
        return list(self.detecciones)


class ReconocedorDlib:
    nombre = "dlib"

    def __init__(
        self, carpeta_rostros: Path | str, tolerancia: float = TOLERANCIA
    ) -> None:
        import face_recognition

        self._fr = face_recognition
        self.tolerancia = tolerancia
        self.nombres: list[str] = []
        self.encodings: list[np.ndarray] = []
        self._cargar(Path(carpeta_rostros))

    def _cargar(self, carpeta: Path) -> None:
        carpeta.mkdir(parents=True, exist_ok=True)
        for archivo in sorted(carpeta.iterdir()):
            if archivo.suffix.lower() not in EXTENSIONES_VALIDAS:
                continue
            with LOCK_DLIB:
                imagen = self._fr.load_image_file(str(archivo))
                encodings = self._fr.face_encodings(imagen)
            if encodings:
                self.nombres.append(archivo.stem)
                self.encodings.append(encodings[0])
            else:
                log.warning("Sin rostro detectable en %s", archivo.name)
        log.info("Rostros conocidos cargados: %d", len(self.nombres))

    def reconocer(self, rgb: np.ndarray) -> list[Deteccion]:
        rgb = np.ascontiguousarray(rgb)
        with LOCK_DLIB:
            cajas = self._fr.face_locations(rgb)
            encodings = self._fr.face_encodings(rgb, cajas)
            resultado = []
            for caja, enc in zip(cajas, encodings, strict=True):
                if not self.encodings:
                    resultado.append(Deteccion(DESCONOCIDO, None, caja))
                    continue
                distancias = self._fr.face_distance(self.encodings, enc)
                i = int(np.argmin(distancias))
                d = float(distancias[i])
                nombre = self.nombres[i] if d <= self.tolerancia else DESCONOCIDO
                resultado.append(Deteccion(nombre, d, caja))
        return resultado


def crear_reconocedor(
    carpeta_rostros: Path | str, forzar_falso: bool = False
) -> Reconocedor:
    """dlib si importa; si no, el reconocedor falso (con aviso)."""
    if not forzar_falso:
        try:
            return ReconocedorDlib(carpeta_rostros)
        except ImportError as e:
            log.error(
                "face_recognition no importa (%s): se usa el reconocedor falso", e
            )
    return ReconocedorFalso()
