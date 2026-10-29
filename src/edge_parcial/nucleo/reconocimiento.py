"""Alerta del quórum -> fotogramas de las fuentes -> servicio de rostros -> reconocimientos.csv.

El núcleo es el escritor único de reconocimientos.csv (docs/CONTRATO_DATOS.md). El trabajo
corre en un hilo aparte para no retrasar la decisión de la siguiente ventana; si el trabajo
anterior sigue en curso, la nueva alerta se descarta (y se anota), nunca se encola.
"""

import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from edge_parcial.csv_anexar import ruta_libre
from edge_parcial.panel.datos import COLUMNAS_RECONOCIMIENTOS, EscritorCSV
from edge_parcial.rostros.anotar import anotar_jpeg
from edge_parcial.rostros.cliente import consultar_servicio

MAX_EDAD_S = 2.0  # el fotograma de la fuente no puede ser más viejo que esto
SIN_ROSTRO = "sin_rostro"  # identidad de la fila cuando la fuente votó pero no se vio ningún rostro


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
        self._escritura = (
            threading.Lock()
        )  # alerta y reconocimiento continuo escriben el mismo CSV
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
                # Una fuente que votó movimiento siempre deja foto y fila: con el nombre si se vio
                # un rostro, o `sin_rostro` si no (el original se conserva sin cuadro).
                self.registrar(ventana, f, jpeg, caras)
        finally:
            self._ocupado.release()

    def registrar(
        self, ventana: int | str, fuente: str, jpeg: bytes, caras: list[dict]
    ) -> None:
        ahora = datetime.now().astimezone()
        archivo = f"{fuente}_{ahora:%Y%m%d_%H%M%S_%f}"[:-3] + ".jpg"
        try:
            self.carpeta.mkdir(parents=True, exist_ok=True)
            destino = ruta_libre(self.carpeta / archivo)
            archivo = destino.name
            anotada = anotar_jpeg(jpeg, caras) if caras else None
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
        filas = caras or [{"identidad": SIN_ROSTRO}]
        with self._escritura:
            for c in filas:
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


class ReconocimientoContinuo:
    """Reconoce las fuentes aunque no haya alerta: si hay alguien delante, queda registrado.

    Cada `periodo_s` toma el último fotograma de cada fuente y lo manda al servicio de rostros.
    Solo se registran las caras vistas (sin filas `sin_rostro`) y, para no llenar el CSV, la
    misma identidad en la misma fuente se anota como mucho cada `repetir_s` segundos.
    """

    def __init__(
        self,
        despachador: DespachadorRostros,
        fuentes: tuple[str, ...] = ("esp32", "droidcam", "local"),
        periodo_s: float = 1.0,
        repetir_s: float = 10.0,
        ventana_actual: Callable[[], int | str] = lambda: "",
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self.d = despachador
        self.fuentes = fuentes
        self.periodo_s = periodo_s
        self.repetir_s = repetir_s
        self.ventana_actual = ventana_actual
        self._reloj = reloj
        self._ultimo_registro: dict[tuple[str, str], float] = {}
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None

    def iniciar(self) -> None:
        self._hilo = threading.Thread(
            target=self._bucle, name="rostros-continuo", daemon=True
        )
        self._hilo.start()

    def detener(self) -> None:
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(3)

    def _bucle(self) -> None:
        while not self._parar.wait(self.periodo_s):
            self.una_pasada()

    def una_pasada(self) -> None:
        for f in self.fuentes:
            if self._parar.is_set():
                return
            jpeg = self.d.ultimo(f, MAX_EDAD_S)
            if jpeg is None:
                continue  # sin imagen reciente: no es un error (la fuente puede estar apagada)
            try:
                caras = self.d.consultar(jpeg, f)
            except (OSError, ValueError) as e:
                self.d.error(f"servicio de rostros: {type(e).__name__}: {e}")
                continue
            ahora = self._reloj()
            nuevas = [
                c
                for c in caras
                if ahora - self._ultimo_registro.get((f, c.get("identidad", "")), -1e9)
                >= self.repetir_s
            ]
            if not nuevas:
                continue
            for c in nuevas:
                self._ultimo_registro[(f, c.get("identidad", ""))] = ahora
            self.d.registrar(self.ventana_actual(), f, jpeg, nuevas)
