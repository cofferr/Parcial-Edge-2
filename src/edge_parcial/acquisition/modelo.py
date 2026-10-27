"""Columnas del CSV crudo y resumen de un lector de red."""

import logging
import threading
from dataclasses import dataclass, field

log = logging.getLogger("edge_parcial.lector")

COLUMNAS_FRAMES = [
    "run_id",
    "source",
    "endpoint",
    "condition",
    "seq",
    "warmup",
    "conexion",
    "t_request_ns",
    "t_first_ns",
    "t_last_ns",
    "t_decode_ini_ns",
    "t_ready_ns",
    "t_encode_ini_ns",
    "t_encode_fin_ns",
    "n_recv",
    "payload_bytes",
    "header_bytes",
    "raw_bytes",
    "jpeg_valid",
    "width",
    "height",
    "capture_us",
    "flush_us",
    "jpeg_us",
    "rssi_dbm",
    "fw",
    "bytes_recv_total",
    "cabeceras_faltantes",
    "descartado",
    "error",
]

COLUMNAS_EVENTOS = [
    "run_id",
    "source",
    "endpoint",
    "t_ns",
    "tipo",
    "conexion",
    "bytes_parciales",
    "bytes_recv_total",
    "detalle",
]

# Cabecera X-* -> columna del CSV, y nombre canónico para los avisos.
CABECERAS_X = {
    "x-capture-us": "capture_us",
    "x-jpeg-us": "jpeg_us",
    "x-rssi-dbm": "rssi_dbm",
    "x-flush-us": "flush_us",
}
NOMBRE_CABECERA = {
    "x-capture-us": "X-Capture-Us",
    "x-jpeg-us": "X-Jpeg-Us",
    "x-rssi-dbm": "X-Rssi-Dbm",
    "x-flush-us": "X-Flush-Us",
}


def fila_vacia() -> dict:
    return dict.fromkeys(COLUMNAS_FRAMES)


def evento_vacio() -> dict:
    return dict.fromkeys(COLUMNAS_EVENTOS)


@dataclass
class Resumen:
    """Resumen de un lector. Seguro entre hilos."""

    source: str
    endpoint: str
    esperadas: tuple = ()
    fotogramas: int = 0  # filas de fotograma (incluye warmup y descartados)
    descartes: int = 0  # descartados por cola llena del decodificador
    reconexiones: int = 0
    errores: int = 0  # muestras con error, JPEG inválido o protocolo
    n_recv_1: int = 0  # fotogramas con n_recv == 1 (ttx = 0 es solo resolución)
    abandonada: bool = False
    # Hubo una reconexión entre fotogramas medidos (warmup=0): no se promedia en silencio.
    con_reconexiones: bool = False
    # Cámara local: resolución pedida y real (shape del primer fotograma).
    resolucion_solicitada: tuple | None = None
    resolucion_real: tuple | None = None
    motivos_extra: list = field(default_factory=list)
    cabeceras_faltantes: dict = field(default_factory=dict)  # nombre -> filas
    bytes_recv_por_conexion: list = field(default_factory=list)
    advertencias: list = field(default_factory=list)  # una vez por tipo
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def registrar_faltantes(
        self, nombres: list[str], crudos: dict | None = None
    ) -> None:
        """Cuenta cabeceras ausentes o inválidas; avisa una vez por tipo.

        `crudos` trae el valor recibido de las cabeceras presentes pero inválidas.
        """
        crudos = crudos or {}
        with self._lock:
            for n in nombres:
                if n not in self.cabeceras_faltantes:
                    if n in crudos:
                        msg = f"[{self.source}{self.endpoint}] cabecera {n} inválida, valor crudo {crudos[n]!r}"
                    else:
                        msg = f"[{self.source}{self.endpoint}] falta la cabecera {n}"
                    self.advertencias.append(msg)
                    log.warning(msg)
                self.cabeceras_faltantes[n] = self.cabeceras_faltantes.get(n, 0) + 1

    def sumar(self, **campos: int) -> None:
        with self._lock:
            for k, v in campos.items():
                setattr(self, k, getattr(self, k) + v)

    @property
    def bytes_recv_total(self) -> int:
        return sum(self.bytes_recv_por_conexion)

    def motivos_invalida(self) -> list[str]:
        """Motivos por los que la corrida de esta fuente es inválida."""
        motivos = []
        if self.abandonada:
            motivos.append("fuente abandonada tras agotar los reintentos")
        if self.esperadas and self.cabeceras_faltantes:
            falt = ", ".join(sorted(self.cabeceras_faltantes))
            motivos.append(f"cabeceras obligatorias ausentes: {falt}")
        return motivos + list(self.motivos_extra)

    def a_dict(self) -> dict:
        return {
            "source": self.source,
            "endpoint": self.endpoint,
            "fotogramas": self.fotogramas,
            "descartes": self.descartes,
            "reconexiones": self.reconexiones,
            "errores": self.errores,
            "n_recv_1": self.n_recv_1,
            "abandonada": self.abandonada,
            "con_reconexiones": self.con_reconexiones,
            "resolucion_solicitada": self.resolucion_solicitada,
            "resolucion_real": self.resolucion_real,
            "cabeceras_faltantes": dict(self.cabeceras_faltantes),
            "bytes_recv_por_conexion": list(self.bytes_recv_por_conexion),
            "bytes_recv_total": self.bytes_recv_total,
            "advertencias": list(self.advertencias),
            "motivos_invalida": self.motivos_invalida(),
        }
