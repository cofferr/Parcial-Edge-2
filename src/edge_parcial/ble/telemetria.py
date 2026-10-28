"""Escritor único de telemetria.csv (contrato de datos): solo añade, flush por fila."""

import csv
from datetime import datetime
from pathlib import Path

from edge_parcial.ble.trama import Lectura

COLUMNAS = [
    "timestamp",
    "temperatura_c",
    "humedad_pct",
    "suelo_adc",
    "movimiento",
    "foto",
    "trama_hex",
]


class EscritorTelemetria:
    def __init__(self, ruta: Path | str) -> None:
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        # Cabecera una sola vez, al crear el archivo.
        if not self.ruta.exists() or self.ruta.stat().st_size == 0:
            self._escribir(COLUMNAS)

    def _escribir(self, fila: list) -> None:
        with open(self.ruta, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(fila)
            f.flush()

    def agregar(self, ts: datetime, lectura: Lectura, trama: bytes) -> None:
        """La columna foto queda vacía: la evidencia la pone el núcleo al integrar."""
        self._escribir(
            [
                ts.isoformat(timespec="seconds"),
                f"{lectura.temperatura_c:.2f}",
                f"{lectura.humedad_pct:.2f}",
                "" if lectura.suelo_adc is None else lectura.suelo_adc,
                lectura.movimiento,
                "",
                trama.hex(" "),
            ]
        )
