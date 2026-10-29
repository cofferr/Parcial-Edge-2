"""Alerta del quórum -> fotogramas de las fuentes -> servicio de rostros -> reconocimientos.csv.

El núcleo es el escritor único de reconocimientos.csv (docs/CONTRATO_DATOS.md). El trabajo
corre en un hilo aparte para no retrasar la decisión de la siguiente ventana; si el trabajo
anterior sigue en curso, la nueva alerta se descarta (y se anota), nunca se encola.
"""

import http.client
import json
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from edge_parcial.csv_anexar import ruta_libre
from edge_parcial.panel.datos import COLUMNAS_RECONOCIMIENTOS, EscritorCSV
from edge_parcial.rostros.servicio import HOST, PUERTO

MAX_EDAD_S = 2.0  # el fotograma de la fuente no puede ser más viejo que esto
TIMEOUT_S = 15.0  # el reconocimiento facial (dlib) puede tardar


def consultar_servicio(jpeg: bytes, fuente: str, puerto: int = PUERTO) -> list[dict]:
    """POST /reconocer: devuelve las caras. Lanza OSError/ValueError si falla."""
    con = http.client.HTTPConnection(HOST, puerto, timeout=TIMEOUT_S)
    try:
        con.request(
            "POST", f"/reconocer?fuente={fuente}", jpeg, {"Content-Type": "image/jpeg"}
        )
        r = con.getresponse()
        cuerpo = r.read()
    finally:
        con.close()
    if r.status != 200:
        raise OSError(f"servicio de rostros respondió {r.status}")
    return list(json.loads(cuerpo).get("caras", []))


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
