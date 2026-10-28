"""Registro crudo de la latencia por capas (Tarea 2.4): un CSV por fotograma y otro por ventana.

Marcas en `perf_counter_ns` sin redondear. Un solo escritor por archivo con candado
(los hilos del edge y del fog entregan filas); `flush` periódico.
"""

import csv
import threading
from pathlib import Path

FUENTES = ("esp32", "droidcam", "local")
COLUMNAS_FOTOGRAMAS = [
    "source", "seq", "ventana", "t_request_ns", "t_first_ns", "t_ready_ns",
    "t_edge_ini_ns", "t_edge_fin_ns", "capture_us", "flush_us", "jpeg_us",
    "evaluado", "fraccion", "luminancia", "movimiento", "cambio_global", "tapada", "tardio",
]  # fmt: skip
COLUMNAS_VENTANAS = [
    "ventana", "t_ini_ns", "t_decision_ns", "ts_wall", "Q", "n_true", "alerta",
    *[f"{c}_{f}" for f in FUENTES for c in ("voto", "bandera", "fraccion", "n_fotogramas", "t_voto_ns")],
]  # fmt: skip
_FLUSH_CADA = 50


class _CSV:
    def __init__(self, ruta: Path, columnas: list[str]) -> None:
        self._f = open(ruta, "w", encoding="utf-8", newline="")  # noqa: SIM115 - queda abierto
        self._w = csv.DictWriter(self._f, columnas, lineterminator="\n")
        self._w.writeheader()
        self._lock = threading.Lock()
        self._n = 0

    def fila(self, datos: dict) -> None:
        with self._lock:
            if self._f.closed:
                return
            self._w.writerow(datos)
            self._n += 1
            if self._n % _FLUSH_CADA == 0:
                self._f.flush()

    def cerrar(self) -> None:
        with self._lock:
            self._f.close()


class RegistroCapas:
    def __init__(self, directorio: Path | str) -> None:
        self.directorio = Path(directorio)
        self.directorio.mkdir(parents=True, exist_ok=True)
        self.ruta_fotogramas = self.directorio / "capas_fotogramas.csv"
        self.ruta_ventanas = self.directorio / "capas_ventanas.csv"
        self._fotogramas = _CSV(self.ruta_fotogramas, COLUMNAS_FOTOGRAMAS)
        self._ventanas = _CSV(self.ruta_ventanas, COLUMNAS_VENTANAS)

    def fotograma(self, datos: dict) -> None:
        self._fotogramas.fila(datos)

    def decision(self, d) -> None:
        fila = {
            "ventana": d.ventana, "t_ini_ns": d.t_ini_ns,
            "t_decision_ns": d.t_decision_ns, "ts_wall": d.ts_wall,
            "Q": d.q, "n_true": d.n_true, "alerta": int(d.alerta),
        }  # fmt: skip
        for f, v in d.votos.items():
            fila[f"voto_{f}"] = int(v.voto)
            fila[f"bandera_{f}"] = v.bandera
            fila[f"fraccion_{f}"] = v.fraccion
            fila[f"n_fotogramas_{f}"] = v.n_fotogramas
            fila[f"t_voto_ns_{f}"] = v.t_voto_ns or ""
        self._ventanas.fila(fila)

    def cerrar(self) -> None:
        self._fotogramas.cerrar()
        self._ventanas.cerrar()
