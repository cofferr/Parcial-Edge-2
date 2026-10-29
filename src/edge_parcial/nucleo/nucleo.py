"""Núcleo: device -> edge -> fog en un mismo proceso (docs/DISENO.md §24 y §25).

Las capas son módulos lógicos; entre ellas solo hay colas en memoria (no se simula red).
El núcleo crea la rejilla de ventanas (`t0` en `perf_counter_ns`), un `TrabajadorEdge` por
fuente, el `Fog`, el latido de estado.json y conecta las entradas. Escribe eventos.csv y
estado.json según docs/CONTRATO_DATOS.md y una línea de log por ventana.
"""

import threading
from collections import deque
from dataclasses import replace
from pathlib import Path
from time import perf_counter_ns

from edge_parcial.edge.trabajador import TrabajadorEdge
from edge_parcial.fog.decision import Fog
from edge_parcial.fog.quorum import quorum
from edge_parcial.fog.rejilla import Rejilla
from edge_parcial.nucleo.config_p2 import ConfigP2
from edge_parcial.nucleo.evidencia import LectorEvidenciaPIR
from edge_parcial.nucleo.modelo import Decision
from edge_parcial.nucleo.salidas import (
    FUENTES,
    EventosCSV,
    ahora_iso,
    entrada_estado,
    estado_completo,
    linea_log,
)
from edge_parcial.panel.control import MARCA_DESACTIVADO, quorum_activo
from edge_parcial.panel.estado import fusionar_estado

_FRESCURA_NS = 3_000_000_000  # una cámara sin fotogramas durante 3 s no está viva


class ErrorNucleo(Exception):
    """Configuración incoherente (por ejemplo, N distinto del número de fuentes)."""


class Nucleo:
    def __init__(
        self,
        cfg: ConfigP2,
        entradas: dict,
        run_id: str,
        ruta_eventos: Path | str,
        ruta_estado: Path | str | None,
        *,
        capas=None,
        consola=print,
        reloj=perf_counter_ns,
        latido_s: float = 1.0,
        publicador=None,
        despachador=None,
        continuo=None,
        ruta_telemetria: Path | str | None = None,
        ruta_control: Path | str | None = None,
    ) -> None:
        if len(entradas) != cfg.n_quorum or not set(entradas) <= set(FUENTES):
            raise ErrorNucleo(
                f"N de la config ({cfg.n_quorum}) no coincide con las fuentes {sorted(entradas)}"
            )
        self.cfg = cfg
        self.entradas = entradas
        self.fuentes = tuple(f for f in FUENTES if f in entradas)
        self.q = quorum(cfg.n_quorum)  # Q sale de N de la config, nunca fijo
        self.run_id = run_id
        self.capas = capas
        self.consola = consola
        self.reloj = reloj
        self.latido_s = latido_s
        self.ruta_estado = Path(ruta_estado) if ruta_estado else None
        self.eventos = EventosCSV(ruta_eventos, run_id)
        self.historial: list[Decision] = []
        self.ultima: Decision | None = None
        self.rejilla: Rejilla | None = None
        self.trabajadores: dict[str, TrabajadorEdge] = {}
        self.fog: Fog | None = None
        self._errores: deque[str] = deque(maxlen=5)
        self._parar = threading.Event()
        self._hilo_latido: threading.Thread | None = None
        self._iniciado = False
        self.publicador = publicador
        self.despachador = despachador
        self.continuo = continuo
        if continuo is not None:
            continuo.ventana_actual = lambda: self.ultima.ventana if self.ultima else ""
        if despachador is not None:
            despachador.error = self.anotar_error
        self.evidencia = LectorEvidenciaPIR(ruta_telemetria)
        self.ruta_control = ruta_control

    # -- ciclo de vida ------------------------------------------------------

    def iniciar(self) -> None:
        for e in self.entradas.values():
            e.abrir()  # la cámara local se abre en el hilo principal
        cfg = self.cfg
        ventana_ns = int(cfg.ventana_s * 1e9)
        gracia_ns = int(cfg.gracia_s * 1e9)
        self.rejilla = Rejilla(self.reloj(), ventana_ns)
        self.fog = Fog(
            self.fuentes, self.q, self.rejilla, gracia_ns,
            int(cfg.timeout_fog_s * 1e9), self._al_decidir, self.reloj,
        )  # fmt: skip
        reg = self.capas.fotograma if self.capas is not None else None
        for f in self.fuentes:
            self.trabajadores[f] = TrabajadorEdge(
                f, cfg.detector[f], self.rejilla, gracia_ns, self.fog.recibir, reg,
                reloj=self.reloj,
            )  # fmt: skip
        self.fog.start()
        for t in self.trabajadores.values():
            t.start()
        self._escribir_estado()
        self._hilo_latido = threading.Thread(target=self._latido, name="latido", daemon=True)  # fmt: skip
        self._hilo_latido.start()
        for f in self.fuentes:
            self.entradas[f].iniciar(self.trabajadores[f].encolar)
        self._iniciado = True
        if self.continuo is not None:
            self.continuo.iniciar()
        if self.publicador is not None:
            self.publicador.iniciar()
            if "local" in self.trabajadores:
                # La local es la única que se codifica (una vez, calidad ~70).
                local = self.trabajadores["local"]
                self.publicador.codificar_periodico(
                    "local", lambda: local.ultima_imagen
                )

    def detener(self) -> None:
        if self.continuo is not None:
            self.continuo.detener()
        if self.publicador is not None:
            self.publicador.detener()
        for e in self.entradas.values():
            e.detener()
        for t in self.trabajadores.values():
            t.detener()
        if self.fog is not None:
            self.fog.detener()
        self._parar.set()
        for t in (*self.trabajadores.values(), self.fog, self._hilo_latido):
            if t is not None:
                t.join(3)
        self._iniciado = False
        self._escribir_estado()
        self.eventos.cerrar()
        if self.capas is not None:
            self.capas.cerrar()

    def __enter__(self):
        self.iniciar()
        return self

    def __exit__(self, *args) -> None:
        self.detener()

    def anotar_error(self, mensaje: str) -> None:
        self._errores.append(mensaje)

    # -- decisión y salidas ---------------------------------------------------

    def _al_decidir(self, d: Decision) -> None:
        # Quórum desactivado desde el panel (control.json): los votos se calculan y se
        # registran igual, pero no hay alerta ni reconocimiento y la ventana queda marcada.
        activo = quorum_activo(self.ruta_control)
        efectiva = d if activo else replace(d, alerta=False)
        marca = "" if activo else MARCA_DESACTIVADO
        self.ultima = efectiva
        self.historial.append(d)  # la decisión medida, sin tocar
        if self.capas is not None:
            self.capas.decision(d)
        try:
            self.eventos.escribir(efectiva, marca, self.evidencia.nueva())
        except OSError as e:
            self._errores.append(f"eventos.csv: {e}")
        if efectiva.alerta and self.despachador is not None:
            # Fotogramas de las fuentes que votaron movimiento -> servicio de rostros.
            votantes = [f for f, v in d.votos.items() if v.voto]
            self.despachador.disparar(d.ventana, votantes)
        self.consola(linea_log(efectiva, self.fuentes))

    def estado_visual(self) -> dict:
        """Última decisión e imagen de cada fuente (para la superposición `--ventanas`)."""
        d = self.ultima
        fuentes = {}
        for f, t in self.trabajadores.items():
            v = d.votos.get(f) if d else None
            fuentes[f] = {
                "img": t.ultima_imagen,
                "voto": None if v is None else v.voto,
                "bandera": None if v is None else v.bandera,
            }
        return {
            "ventana": None if d is None else d.ventana,
            "q": self.q,
            "n_true": None if d is None else d.n_true,
            "alerta": bool(d and d.alerta),
            "fuentes": fuentes,
        }

    # -- latido ------------------------------------------------------------------

    def snapshot_estado(self) -> dict:
        ahora = self.reloj()
        camaras = {}
        for f, t in self.trabajadores.items():
            reciente = bool(t.marcas_ns) and ahora - t.marcas_ns[-1] <= _FRESCURA_NS
            camaras[f] = entrada_estado(
                self.entradas[f].viva() and reciente,
                round(t.fps(), 2),
                t.ultima_marca_wall,
                self.entradas[f].errores() + list(t.errores),
            )
        nucleo = entrada_estado(self._iniciado, None, ahora_iso(), list(self._errores))
        return estado_completo(camaras, nucleo)

    def _escribir_estado(self) -> None:
        if self.ruta_estado is None:
            return
        try:
            # `ble` y `servicio_rostros` son de otros procesos: solo se marcan como no
            # reportados si todavía no existen, nunca se pisa su latido.
            completo = self.snapshot_estado()
            ajenos = ("ble", "servicio_rostros")
            fusionar_estado(
                self.ruta_estado,
                {k: v for k, v in completo.items() if k not in ajenos},
                {k: completo[k] for k in ajenos},
            )
        except OSError as e:
            self._errores.append(f"estado.json: {e}")

    def _latido(self) -> None:
        while not self._parar.wait(self.latido_s):
            self._escribir_estado()
