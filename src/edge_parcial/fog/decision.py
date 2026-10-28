"""Hilo del fog: junta los votos de cada ventana y decide la alerta (docs/DISENO.md §24).

La ventana k se decide cuando llegan los N votos o, si una fuente no entrega, cuando
pasa `timeout_ns` desde el momento en que debía estar emitido (fin de la ventana +
gracia): la ausente cuenta False con bandera `caida`. Las ventanas se deciden en orden.
`t_decision_ns` se sella justo al calcular la alerta, antes de escribir o imprimir.
"""

import queue
import threading
from datetime import datetime
from time import perf_counter_ns

from edge_parcial.fog.quorum import decidir
from edge_parcial.fog.rejilla import Rejilla
from edge_parcial.nucleo.modelo import Decision, VotoVentana

BANDERA_CAIDA = "caida"
_TICK_S = 0.01


class Fog(threading.Thread):
    def __init__(
        self,
        fuentes: tuple[str, ...],
        q: int,
        rejilla: Rejilla,
        gracia_ns: int,
        timeout_ns: int,
        al_decidir,
        reloj=perf_counter_ns,
    ) -> None:
        super().__init__(name="fog", daemon=True)
        self.fuentes = fuentes
        self.q = q
        self.rejilla = rejilla
        self.gracia_ns = gracia_ns
        self.timeout_ns = timeout_ns
        self.al_decidir = al_decidir
        self.reloj = reloj
        self.cola: queue.Queue[VotoVentana] = queue.Queue()
        self._pendientes: dict[int, dict[str, VotoVentana]] = {}
        self._siguiente = 0
        self._parar = threading.Event()

    def recibir(self, voto: VotoVentana) -> None:
        self.cola.put(voto)

    def detener(self) -> None:
        self._parar.set()

    def run(self) -> None:
        while not self._parar.is_set():
            try:
                v = self.cola.get(timeout=_TICK_S)
                if (
                    v.ventana >= self._siguiente
                ):  # un voto de una ventana ya decidida se ignora
                    self._pendientes.setdefault(v.ventana, {})[v.source] = v
            except queue.Empty:
                pass
            self._decidir_listas()

    def _decidir_listas(self) -> None:
        while True:
            k = self._siguiente
            votos = self._pendientes.get(k, {})
            vencida = (
                self.reloj() >= self.rejilla.fin(k) + self.gracia_ns + self.timeout_ns
            )
            if len(votos) < len(self.fuentes) and not vencida:
                return
            self._siguiente += 1
            self._pendientes.pop(k, None)
            self.al_decidir(self.decidir_ventana(k, votos))

    def decidir_ventana(self, k: int, votos: dict[str, VotoVentana]) -> Decision:
        """Quórum de la ventana k; una fuente ausente cuenta False (`caida`)."""
        completos = {}
        caidas = []
        for f in self.fuentes:
            if f in votos:
                completos[f] = votos[f]
            else:
                caidas.append(f)
                completos[f] = VotoVentana(
                    f, k, False, BANDERA_CAIDA, float("nan"), 0, 0
                )
        n_true, alerta = decidir([v.voto for v in completos.values()], self.q)
        t_decision = self.reloj()
        return Decision(
            ventana=k,
            t_ini_ns=self.rejilla.inicio(k),
            q=self.q,
            votos=completos,
            n_true=n_true,
            alerta=alerta,
            t_decision_ns=t_decision,
            ts_wall=datetime.now().astimezone().isoformat(),
            caidas=caidas,
        )
