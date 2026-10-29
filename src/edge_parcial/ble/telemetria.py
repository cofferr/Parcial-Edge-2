"""Escritor único de telemetria.csv (contrato de datos): solo añade, flush por fila."""

import csv
from datetime import datetime
from pathlib import Path

from edge_parcial.ble.trama import Lectura
from edge_parcial.csv_anexar import preparar_csv
from edge_parcial.sesion import sesion_actual

COLUMNAS = [
    "timestamp",
    "temperatura_c",
    "humedad_pct",
    "suelo_adc",
    "movimiento",
    "foto",
    "trama_hex",
    "session_id",
]


class EscritorTelemetria:
    def __init__(self, ruta: Path | str) -> None:
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        # Solo anexar: se conserva el archivo; si cambió la cabecera, el viejo se aparta.
        if preparar_csv(self.ruta, COLUMNAS):
            self._escribir(COLUMNAS)

    def _escribir(self, fila: list) -> None:
        with open(self.ruta, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(fila)
            f.flush()

    def agregar(
        self, ts: datetime, lectura: Lectura, trama: bytes, foto: str = ""
    ) -> None:
        """`foto`: nombre del JPEG de evidencia (vacío si no hubo movimiento o falló)."""
        self._escribir(
            [
                ts.isoformat(timespec="seconds"),
                f"{lectura.temperatura_c:.2f}",
                f"{lectura.humedad_pct:.2f}",
                "" if lectura.suelo_adc is None else lectura.suelo_adc,
                lectura.movimiento,
                foto,
                trama.hex(" "),
                sesion_actual(),
            ]
        )
