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

from edge_parcial.config import RAIZ

CARPETA_ROSTROS = RAIZ / "rostros_conocidos"  # fuera de git: son datos faciales
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
        self.carpeta = Path(carpeta_rostros)
        self.nombres: list[str] = []
        self.encodings: list[np.ndarray] = []
        self._firma: tuple = ()
        self._cargar()

    def _archivos(self) -> list[tuple[str, Path]]:
        """(identidad, archivo): `Ana.jpg` -> Ana; `Ana/1.jpg`, `Ana/2.jpg` -> Ana (muestras)."""
        self.carpeta.mkdir(parents=True, exist_ok=True)
        encontrados = []
        for entrada in sorted(self.carpeta.iterdir()):
            if entrada.name.startswith(("_", ".")):
                continue  # _archivo: personas dadas de baja
            if entrada.is_dir():
                encontrados += [
                    (entrada.name, a)
                    for a in sorted(entrada.iterdir())
                    if a.suffix.lower() in EXTENSIONES_VALIDAS
                ]
            elif entrada.suffix.lower() in EXTENSIONES_VALIDAS:
                encontrados.append((entrada.stem, entrada))
        return encontrados

    def _cargar(self) -> None:
        archivos = self._archivos()
        nombres, encodings = [], []
        for identidad, archivo in archivos:
            with LOCK_DLIB:
                imagen = self._fr.load_image_file(str(archivo))
                encs = self._fr.face_encodings(imagen)
            if encs:
                nombres.append(identidad)
                encodings.append(encs[0])
            else:
                log.warning("Sin rostro detectable en %s", archivo.name)
        self.nombres, self.encodings = (
            nombres,
            encodings,
        )  # reemplazo atómico de las listas
        self._firma = self._firma_actual(archivos)
        log.info("Rostros conocidos cargados: %d", len(self.nombres))

    @staticmethod
    def _firma_actual(archivos: list[tuple[str, Path]]) -> tuple:
        firma = []
        for _, a in archivos:
            try:
                s = a.stat()
            except OSError:
                continue
            firma.append((str(a), s.st_mtime_ns, s.st_size))
        return tuple(firma)

    def recargar_si_cambio(self) -> bool:
        """Recarga los conocidos si cambió la carpeta (altas o bajas del panel, sin reiniciar)."""
        if self._firma_actual(self._archivos()) == self._firma:
            return False
        self._cargar()
        return True

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
