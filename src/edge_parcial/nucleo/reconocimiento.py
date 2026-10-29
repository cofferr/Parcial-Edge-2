"""Alerta del quórum -> fotogramas de las fuentes -> servicio de rostros -> reconocimientos.csv.

El núcleo es el escritor único de reconocimientos.csv (docs/CONTRATO_DATOS.md). El trabajo
corre en un hilo aparte para no retrasar la decisión de la siguiente ventana; si el trabajo
anterior sigue en curso, la nueva alerta se descarta (y se anota), nunca se encola.
"""

import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from edge_parcial.csv_anexar import ruta_libre
from edge_parcial.panel.datos import COLUMNAS_RECONOCIMIENTOS, EscritorCSV
from edge_parcial.rostros.anotar import anotar_jpeg
from edge_parcial.rostros.cliente import consultar_servicio

MAX_EDAD_S = 2.0  # el fotograma de la fuente no puede ser más viejo que esto


class DespachadorRostros:
    def __init__(
        self,
        ultimo: Callable[[str, float], bytes | None],
        carpeta_snapshots: Path | str,
        ruta_reconocimientos: Path | str,
        error: Callable[[str], None],
        consultar: Callable[[bytes, str], list[dict]] = consultar_servicio,
    ) -> None:
        self.ultimo = ultimo
        self.carpeta = Path(carpeta_snapshots)
        self.escritor = EscritorCSV(ruta_reconocimientos, COLUMNAS_RECONOCIMIENTOS)
        self.error = error
        self.consultar = consultar
        self._ocupado = threading.Lock()
        self._hilo: threading.Thread | None = None

    def disparar(self, ventana: int, fuentes: list[str]) -> None:
        """No bloquea. `fuentes`: las que votaron movimiento en la ventana de la alerta."""
        if not self._ocupado.acquire(blocking=False):
            self.error(
                f"reconocimiento de la ventana {ventana} descartado: el anterior sigue"
            )
            return
        self._hilo = threading.Thread(
            target=self._trabajo,
            args=(ventana, list(fuentes)),
            name="rostros",
            daemon=True,
        )
        self._hilo.start()

    def esperar(self, timeout: float = 5.0) -> None:
        if self._hilo is not None:
            self._hilo.join(timeout)

    def _trabajo(self, ventana: int, fuentes: list[str]) -> None:
        try:
            for f in fuentes:
                jpeg = self.ultimo(f, MAX_EDAD_S)
                if jpeg is None:
                    self.error(f"sin fotograma reciente de {f} para reconocer")
                    continue
                try:
                    caras = self.consultar(jpeg, f)
                except (OSError, ValueError) as e:
                    self.error(f"servicio de rostros: {type(e).__name__}: {e}")
                    continue
                if caras:
                    self._registrar(ventana, f, jpeg, caras)
        finally:
            self._ocupado.release()

    def _registrar(
        self, ventana: int, fuente: str, jpeg: bytes, caras: list[dict]
    ) -> None:
        ahora = datetime.now().astimezone()
        archivo = f"{fuente}_{ahora:%Y%m%d_%H%M%S_%f}"[:-3] + ".jpg"
        try:
            self.carpeta.mkdir(parents=True, exist_ok=True)
            destino = ruta_libre(self.carpeta / archivo)
            archivo = destino.name
            anotada = anotar_jpeg(jpeg, caras)
            if anotada is not None:
                # La foto de evidencia lleva el cuadro con el nombre; el original se conserva.
                destino.write_bytes(anotada)
                original = ruta_libre(
                    destino.with_name(f"{destino.stem}_sin_anotar.jpg")
                )
                original.write_bytes(jpeg)
            else:
                destino.write_bytes(jpeg)
        except OSError as e:
            self.error(f"snapshot: {e}")
            return
        for c in caras:
            d = c.get("distancia")
            self.escritor.agregar(
                {
                    "ts_wall": ahora.isoformat(timespec="seconds"),
                    "fuente": fuente,
                    "ventana_ref": ventana,
                    "identidad": c.get("identidad", "desconocido"),
                    "distancia": "" if d is None else d,
                    "snapshot": archivo,
                }
            )
