"""Rutas y lectura/escritura tolerante de los archivos del contrato de datos."""

import csv
import io
import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from edge_parcial.ble.telemetria import COLUMNAS
from edge_parcial.config import RAIZ, SNAPSHOTS_DIR_DEFECTO, ErrorConfig, cargar_config

COLUMNAS_TELEMETRIA = COLUMNAS
COLUMNAS_EVENTOS = [
    "run_id",
    "ts_wall",
    "ventana",
    "t_ventana_ini_ns",
    "voto_esp32",
    "voto_droidcam",
    "voto_local",
    "bandera_esp32",
    "bandera_droidcam",
    "bandera_local",
    "Q",
    "n_true",
    "alerta",
    "marca",
    "evidencia_fuente",
    "evidencia_foto",
]
COLUMNAS_RECONOCIMIENTOS = [
    "ts_wall",
    "fuente",
    "ventana_ref",
    "identidad",
    "distancia",
    "snapshot",
]
FUENTES = ("esp32", "droidcam", "local")
VARIABLE_ENTORNO = "EDGE_DATA_DIR"
# "1" = otro proceso (la demo) ya lanza los componentes; el panel no los lanza.
VARIABLE_ORQUESTADO = "EDGE_ORQUESTADO"


@dataclass(frozen=True)
class Rutas:
    base: Path
    snapshots: Path

    @property
    def telemetria(self) -> Path:
        return self.base / "telemetria.csv"

    @property
    def eventos(self) -> Path:
        return self.base / "eventos.csv"

    @property
    def reconocimientos(self) -> Path:
        return self.base / "reconocimientos.csv"

    @property
    def estado(self) -> Path:
        return self.base / "estado.json"

    @property
    def tablas(self) -> Path:
        return self.base / "processed" / "tablas"

    @property
    def figuras(self) -> Path:
        return self.base / "processed"


def rutas_por_defecto(base: Path | str | None = None) -> Rutas:
    """Base: argumento > EDGE_DATA_DIR > data/. Snapshots: clave de la config si existe."""
    explicita = base or os.environ.get(VARIABLE_ENTORNO)
    if explicita:
        # Base explícita (pruebas, simulación): los snapshots viven dentro de ella.
        return Rutas(base=Path(explicita), snapshots=Path(explicita) / "snapshots")
    try:
        snapshots = cargar_config().snapshots_dir
    except ErrorConfig:
        snapshots = RAIZ / SNAPSHOTS_DIR_DEFECTO
    return Rutas(base=RAIZ / "data", snapshots=snapshots)


class EscritorCSV:
    """Escritor de solo añadir: cabecera una vez, fila completa con flush."""

    def __init__(self, ruta: Path | str, columnas: list[str]) -> None:
        self.ruta = Path(ruta)
        self.columnas = columnas
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        if not self.ruta.exists() or self.ruta.stat().st_size == 0:
            self._escribir(columnas)

    def _escribir(self, fila: list) -> None:
        with open(self.ruta, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(fila)
            f.flush()

    def agregar(self, fila: dict) -> None:
        self._escribir([fila.get(c, "") for c in self.columnas])


def leer_csv(ruta: Path | str, ultimas: int | None = None) -> pd.DataFrame:
    """Lee un CSV ignorando una última línea incompleta. Vacío si no existe.

    Todo se lee como texto; el llamador convierte los tipos que necesite.
    """
    try:
        texto = Path(ruta).read_text(encoding="utf-8")
    except OSError:
        return pd.DataFrame()
    lineas = texto.splitlines(keepends=True)
    if lineas and not lineas[-1].endswith("\n"):
        lineas.pop()  # línea a medio escribir: se leerá completa en la siguiente pasada
    if not lineas:
        return pd.DataFrame()
    filas = list(csv.reader(io.StringIO("".join(lineas))))
    cabecera, cuerpo = filas[0], [f for f in filas[1:] if len(f) == len(filas[0])]
    if ultimas is not None:
        cuerpo = cuerpo[max(0, len(cuerpo) - ultimas) :]  # [-0:] devolvería todo
    return pd.DataFrame(cuerpo, columns=cabecera, dtype=str)
