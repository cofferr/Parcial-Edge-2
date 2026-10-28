"""Hilo del edge por fuente: detector por fotograma y emisión del voto de cada ventana.

Los fotogramas se asignan a ventanas por `t_ready` sobre la rejilla común. El voto de la
ventana k se emite cuando el reloj pasa su fin más `gracia_s` (para que terminen de
procesarse los fotogramas de esa ventana); un fotograma que llegue al edge cuando su
ventana ya se votó es **tardío**: se procesa (el detector necesita su estado) y se
registra, pero no entra al voto. Un fotograma anterior a `t0` se ignora.
"""

import queue
import threading
from collections import deque
from datetime import datetime
from time import perf_counter_ns

from edge_parcial.edge.detector import DetectorMovimiento, ParamsDetector, votar
from edge_parcial.fog.rejilla import Rejilla
from edge_parcial.nucleo.modelo import FotogramaEdge, VotoVentana

_TICK_S = 0.01
_VENTANA_FPS_NS = 2_000_000_000


class TrabajadorEdge(threading.Thread):
    def __init__(
        self,
        source: str,
        params: ParamsDetector,
        rejilla: Rejilla,
        gracia_ns: int,
        emitir_voto,
        registro_fotograma=None,
        cola_max: int = 16,
        reloj=perf_counter_ns,
    ) -> None:
        super().__init__(name=f"edge-{source}", daemon=True)
        self.source = source
        self.params = params
        self.rejilla = rejilla
        self.gracia_ns = gracia_ns
        self.emitir_voto = emitir_voto
        self.registro_fotograma = registro_fotograma
        self.reloj = reloj
        self.cola: queue.Queue[FotogramaEdge] = queue.Queue(maxsize=cola_max)
        self.detector = DetectorMovimiento(params)
        self._parar = threading.Event()
        self._proxima = 0  # próxima ventana por emitir
        self._buffer: dict[int, list] = {}
        # Estado observable desde otros hilos (estado.json, ventanas).
        self.ultima_imagen = None
        self.ultima_marca_wall: str | None = None
        self.marcas_ns: deque[int] = deque()
        self.errores: deque[str] = deque(maxlen=5)
        self.descartados = 0
        self.tardios = 0
        self.fotogramas = 0

    def encolar(self, f: FotogramaEdge) -> None:
        """Entrada desde la capa device. Con la cola llena se descarta y se cuenta."""
        try:
            self.cola.put_nowait(f)
        except queue.Full:
            self.descartados += 1

    def detener(self) -> None:
        self._parar.set()

    def fps(self) -> float:
        ahora = self.reloj()
        n = sum(1 for t in list(self.marcas_ns) if ahora - t <= _VENTANA_FPS_NS)
        return n / (_VENTANA_FPS_NS / 1e9)

    def run(self) -> None:
        while not self._parar.is_set():
            try:
                f = self.cola.get(timeout=_TICK_S)
            except queue.Empty:
                f = None
            if f is not None:
                try:
                    self._procesar(f)
                except Exception as e:  # noqa: BLE001 - un fotograma malo no debe matar a la fuente
                    self.errores.append(f"{type(e).__name__}: {e}")
            self._cerrar_vencidas()

    def _procesar(self, f: FotogramaEdge) -> None:
        t_ini = self.reloj()
        res = self.detector.procesar(f.img, f.t_ready_ns)
        t_fin = self.reloj()
        k = self.rejilla.indice(f.t_ready_ns)
        tardio = 0 <= k < self._proxima
        if k >= self._proxima:
            self._buffer.setdefault(k, []).append(res)
        self.tardios += tardio
        self.fotogramas += 1
        self.ultima_imagen = f.img
        self.ultima_marca_wall = datetime.now().astimezone().isoformat()
        self.marcas_ns.append(t_fin)
        while self.marcas_ns and t_fin - self.marcas_ns[0] > _VENTANA_FPS_NS:
            self.marcas_ns.popleft()
        if self.registro_fotograma is not None:
            self.registro_fotograma(
                {
                    "source": self.source, "seq": f.seq, "ventana": k,
                    "t_request_ns": f.t_request_ns, "t_first_ns": f.t_first_ns,
                    "t_ready_ns": f.t_ready_ns, "t_edge_ini_ns": t_ini,
                    "t_edge_fin_ns": t_fin, "capture_us": f.capture_us,
                    "flush_us": f.flush_us, "jpeg_us": f.jpeg_us,
                    "evaluado": int(res.evaluado), "fraccion": res.fraccion,
                    "luminancia": res.luminancia, "movimiento": int(res.movimiento),
                    "cambio_global": int(res.cambio_global), "tapada": int(res.tapada),
                    "tardio": int(tardio),
                }
            )  # fmt: skip

    def _cerrar_vencidas(self) -> None:
        """Emite el voto de cada ventana cuyo fin + gracia ya pasó."""
        while self.reloj() >= self.rejilla.fin(self._proxima) + self.gracia_ns:
            k = self._proxima
            self._proxima += 1
            resultados = self._buffer.pop(k, [])
            voto, bandera, frac = votar(resultados, self.params.umbral_voto)
            self.emitir_voto(
                VotoVentana(
                    self.source, k, voto, bandera, frac, len(resultados), self.reloj()
                )
            )
