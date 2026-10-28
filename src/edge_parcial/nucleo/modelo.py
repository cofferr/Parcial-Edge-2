"""Tipos que circulan entre las capas lógicas device -> edge -> fog (un solo proceso)."""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class FotogramaEdge:
    """Fotograma decodificado que entra al edge. Todas las marcas en `perf_counter_ns`."""

    source: str
    seq: int
    t_ready_ns: int
    img: np.ndarray
    t_request_ns: int | None = None
    t_first_ns: int | None = None  # vacío en la cámara local (no hay ttx de red)
    capture_us: int | None = None
    jpeg_us: int | None = None
    flush_us: int | None = None

    @property
    def t_inicio_device_ns(self) -> int | None:
        """Inicio de la capa device: t_first (red) o, en la local, el inicio del read()."""
        return self.t_first_ns if self.t_first_ns is not None else self.t_request_ns


@dataclass(frozen=True)
class VotoVentana:
    """Voto de una fuente en una ventana, ya emitido hacia el fog."""

    source: str
    ventana: int
    voto: bool
    bandera: str
    fraccion: float  # fracción de fotogramas con movimiento (NaN sin datos)
    n_fotogramas: int
    t_voto_ns: int  # instante en que el voto quedó emitido


@dataclass
class Decision:
    """Decisión del quórum para una ventana."""

    ventana: int
    t_ini_ns: int
    q: int
    votos: dict[str, VotoVentana]
    n_true: int
    alerta: bool
    t_decision_ns: int
    ts_wall: str
    caidas: list[str] = field(default_factory=list)  # fuentes que no entregaron voto
