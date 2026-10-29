"""Evidencia del PIR registrada en eventos.csv.

El gateway BLE guarda el JPEG (`pir_<fuente>_<AAAAMMDD_HHMMSS>.jpg`, tomado del último
fotograma compartido por el visor) y pone su nombre en la columna `foto` de telemetria.csv.
El núcleo, único escritor de eventos.csv, lee las filas nuevas de telemetria.csv al cerrar
cada ventana y anota (fuente, archivo) de la última evidencia vista. Lectura tolerante.
"""

import csv
import io
import re
from pathlib import Path

PATRON = re.compile(r"^pir_(?P<fuente>[a-z0-9]+)_\d{8}_\d{6}\.jpg$")
COLA_BYTES = 8192  # solo se mira el final del archivo


class LectorEvidenciaPIR:
    def __init__(self, ruta: Path | str | None) -> None:
        self.ruta = None if ruta is None else Path(ruta)
        self._ultimo_ts = ""  # marca de la última fila ya considerada

    def _filas_nuevas(self) -> list[dict]:
        if self.ruta is None:
            return []
        try:
            with open(self.ruta, "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - COLA_BYTES))
                texto = f.read().decode("utf-8", errors="ignore")
        except OSError:
            return []
        lineas = texto.splitlines(keepends=True)
        if lineas and not lineas[-1].endswith("\n"):
            lineas.pop()  # última línea a medio escribir
        columnas = ["timestamp", "temperatura_c", "humedad_pct", "suelo_adc", "movimiento", "foto", "trama_hex"]  # fmt: skip
        filas = []
        for campos in csv.reader(io.StringIO("".join(lineas))):
            if len(campos) == len(columnas) and campos[0] != "timestamp":
                filas.append(dict(zip(columnas, campos, strict=True)))
        return [f for f in filas if f["timestamp"] > self._ultimo_ts]

    def nueva(self) -> tuple[str, str]:
        """(fuente, archivo) de la última evidencia desde la consulta anterior, o ('', '')."""
        filas = self._filas_nuevas()
        if not filas:
            return "", ""
        self._ultimo_ts = filas[-1]["timestamp"]
        for f in reversed(filas):
            m = PATRON.match(f["foto"])
            if f["movimiento"] == "1" and m:
                return m["fuente"], f["foto"]
        return "", ""
