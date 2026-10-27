"""Escritor único de CSV crudo: data/raw/<run_id>/{frames,eventos}.csv.

Todos los hilos (lectores y decodificadores) entregan sus filas aquí; un solo hilo
escribe, así que las líneas nunca se mezclan. Los valores se escriben tal cual
(marcas en ns sin redondear); None se escribe vacío.
"""

import csv
import queue
import threading
from pathlib import Path
from typing import Self

from edge_parcial.acquisition.modelo import COLUMNAS_EVENTOS, COLUMNAS_FRAMES

_FLUSH_CADA = 50


class RegistroCSV:
    def __init__(self, directorio: Path | str) -> None:
        self.directorio = Path(directorio)
        self.directorio.mkdir(parents=True, exist_ok=True)
        self.ruta_frames = self.directorio / "frames.csv"
        self.ruta_eventos = self.directorio / "eventos.csv"
        self._cola: queue.SimpleQueue = queue.SimpleQueue()
        self._error: BaseException | None = None
        self._hilo = threading.Thread(
            target=self._escribir, name="registro-csv", daemon=True
        )
        self._hilo.start()

    def fila(self, datos: dict) -> None:
        self._encolar("f", datos, COLUMNAS_FRAMES)

    def evento(self, datos: dict) -> None:
        self._encolar("e", datos, COLUMNAS_EVENTOS)

    def _encolar(self, tipo: str, datos: dict, columnas: list[str]) -> None:
        sobran = set(datos) - set(columnas)
        if sobran:
            raise ValueError(f"Columnas desconocidas: {sorted(sobran)}")
        self._cola.put((tipo, dict(datos)))

    def cerrar(self) -> None:
        """Vacía la cola, cierra los archivos y propaga cualquier error de escritura."""
        self._cola.put(None)
        self._hilo.join()
        if self._error is not None:
            raise self._error

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args) -> None:
        self.cerrar()

    def _escribir(self) -> None:
        try:
            with (
                open(self.ruta_frames, "w", newline="", encoding="utf-8") as ff,
                open(self.ruta_eventos, "w", newline="", encoding="utf-8") as fe,
            ):
                wf = csv.DictWriter(ff, COLUMNAS_FRAMES, extrasaction="raise")
                we = csv.DictWriter(fe, COLUMNAS_EVENTOS, extrasaction="raise")
                wf.writeheader()
                we.writeheader()
                n = 0
                while (item := self._cola.get()) is not None:
                    tipo, datos = item
                    (wf if tipo == "f" else we).writerow(datos)
                    n += 1
                    if n % _FLUSH_CADA == 0:
                        ff.flush()
                        fe.flush()
        except BaseException as e:  # noqa: BLE001 - se re-lanza en cerrar()
            self._error = e
            while self._cola.get() is not None:  # no bloquear a los productores
                pass
