"""Lectores de red sobre sockets (sin cv2.VideoCapture), un hilo por fuente.

El hilo lector SOLO lee del socket y sella tiempos: t_recv_ns se toma con
perf_counter_ns inmediatamente después de que recv_into retorne, antes de cualquier
procesamiento. La decodificación va en otro hilo (decodificador.py), conectada por
una cola acotada: si el consumidor se atrasa, se descarta y se cuenta, sin bloquear
el socket.
"""

import logging
import queue
import re
import socket
import threading
import time
from dataclasses import dataclass
from time import perf_counter_ns

from edge_parcial.acquisition.mjpeg import ErrorProtocolo, Fotograma, ParserMJPEG
from edge_parcial.acquisition.modelo import (
    CABECERAS_X,
    NOMBRE_CABECERA,
    Resumen,
    evento_vacio,
    fila_vacia,
)
from edge_parcial.config import Config, ParamsLector

log = logging.getLogger("edge_parcial.lector")

_TICK_S = 0.2  # timeout corto del socket para poder atender la parada


@dataclass(frozen=True)
class SpecFuente:
    source: str  # "esp32" | "droidcam"
    host: str
    puerto: int
    ruta: str  # "/stream" | "/capture" | "/video" (también es la columna endpoint)
    esperadas: tuple = ()  # cabeceras X-* obligatorias (minúsculas)


def spec_esp32_stream(cfg: Config) -> SpecFuente:
    return SpecFuente(
        "esp32",
        cfg.esp32.ip,
        cfg.esp32.puerto,
        "/stream",
        ("x-capture-us", "x-jpeg-us", "x-rssi-dbm"),
    )


def spec_esp32_capture(cfg: Config) -> SpecFuente:
    return SpecFuente(
        "esp32",
        cfg.esp32.ip,
        cfg.esp32.puerto,
        "/capture",
        ("x-capture-us", "x-jpeg-us", "x-rssi-dbm", "x-flush-us"),
    )


def spec_droidcam(cfg: Config) -> SpecFuente:
    return SpecFuente("droidcam", cfg.droidcam.ip, cfg.droidcam.puerto, "/video")


@dataclass
class ItemDecodificar:
    fila: dict
    payload: bytes
    decodificar: bool  # False si el JPEG ya es inválido (SOI/EOI/estructura)


class _Parada(Exception):
    """Se pidió detener el lector."""


_ENTERO_CON_SIGNO = re.compile(r"[+-]?[0-9]+")


def _entero_cabecera(valor: str | None) -> int | None:
    """Entero ASCII con signo opcional (-34, +0). Decimales o texto -> None."""
    if valor is None or not _ENTERO_CON_SIGNO.fullmatch(valor.strip()):
        return None
    return int(valor.strip())


class _LectorBase(threading.Thread):
    def __init__(
        self,
        spec: SpecFuente,
        params: ParamsLector,
        run_id: str,
        condition: str,
        fw: str | None,
        cola: queue.Queue,
        sink_fila,
        sink_evento,
        n_total: int | None = None,
    ) -> None:
        super().__init__(name=f"lector-{spec.source}{spec.ruta}", daemon=True)
        self.spec = spec
        self.params = params
        self.run_id = run_id
        self.condition = condition
        self.fw = fw
        self.cola = cola
        self.sink_fila = sink_fila
        self.sink_evento = sink_evento
        self.n_total = n_total
        self.resumen = Resumen(spec.source, spec.ruta, spec.esperadas)
        self._parar = threading.Event()
        self._seq = 0
        # Solo /stream y /video reconectan; en /capture cada muestra es su conexión.
        self._rastrea_reconexiones = False
        self._conexion_medida: int | None = None

    def detener(self) -> None:
        self._parar.set()

    def _completo(self) -> bool:
        return self.n_total is not None and self._seq >= self.n_total

    def _peticion(self, conexion: str) -> bytes:
        return (
            f"GET {self.spec.ruta} HTTP/1.1\r\nHost: {self.spec.host}:{self.spec.puerto}\r\n"
            f"Accept: */*\r\nConnection: {conexion}\r\n\r\n"
        ).encode()

    def _evento(
        self, tipo: str, conexion=None, parciales=None, total=None, detalle=None
    ):
        e = evento_vacio()
        e.update(
            run_id=self.run_id,
            source=self.spec.source,
            endpoint=self.spec.ruta,
            t_ns=perf_counter_ns(),
            tipo=tipo,
            conexion=conexion,
            bytes_parciales=parciales,
            bytes_recv_total=total,
            detalle=detalle,
        )
        self.sink_evento(e)

    def _fila_base(self, conexion: int, t_request_ns: int | None) -> dict:
        fila = fila_vacia()
        fila.update(
            run_id=self.run_id,
            source=self.spec.source,
            endpoint=self.spec.ruta,
            condition=self.condition,
            seq=self._seq,
            warmup=int(self._seq < self.params.warmup_fotogramas),
            conexion=conexion,
            t_request_ns=t_request_ns,
            fw=self.fw,
            descartado=0,
        )
        self._seq += 1
        return fila

    def _emitir(
        self, f: Fotograma, conexion: int, t_req: int, bytes_total: int
    ) -> None:
        fila = self._fila_base(conexion, t_req)
        fila.update(
            t_first_ns=f.t_first_ns,
            t_last_ns=f.t_last_ns,
            n_recv=f.n_recv,
            payload_bytes=len(f.payload),
            header_bytes=f.header_bytes,
            jpeg_valid=int(f.jpeg_valid),
            bytes_recv_total=bytes_total,
            error=f.error,
        )
        for cab, col in CABECERAS_X.items():
            fila[col] = _entero_cabecera(f.cabeceras.get(cab))
        faltan = [c for c in self.spec.esperadas if fila[CABECERAS_X[c]] is None]
        if faltan:
            nombres = [NOMBRE_CABECERA[c] for c in faltan]
            fila["cabeceras_faltantes"] = ";".join(nombres)
            # Valor crudo de las presentes pero inválidas, para diagnosticar.
            crudos = {
                NOMBRE_CABECERA[c]: f.cabeceras[c] for c in faltan if c in f.cabeceras
            }
            if crudos:
                diag = "; ".join(
                    f"cabecera {n} inválida: {v!r}" for n, v in crudos.items()
                )
                fila["error"] = "; ".join(filter(None, [fila["error"], diag]))
            self.resumen.registrar_faltantes(nombres, crudos)
        if self._rastrea_reconexiones and not fila["warmup"]:
            if self._conexion_medida is None:
                self._conexion_medida = conexion
            elif conexion != self._conexion_medida:
                self.resumen.con_reconexiones = True
        self.resumen.sumar(
            fotogramas=1, n_recv_1=int(f.n_recv == 1), errores=int(f.error is not None)
        )
        item = ItemDecodificar(fila, f.payload, f.jpeg_valid)
        try:
            self.cola.put_nowait(item)
        except queue.Full:
            fila["descartado"] = 1
            self.resumen.sumar(descartes=1)
            self.sink_fila(fila)


class LectorStream(_LectorBase):
    """/stream de la ESP32-CAM o /video de DroidCam, con reconexión y backoff.

    t_request_ns = instante antes de abrir el socket (igual en todas las filas de
    la conexión). `conexion` incrementa en cada reconexión: los fotogramas a cada
    lado no son consecutivos.
    """

    def __init__(self, *args, **kw) -> None:
        super().__init__(*args, **kw)
        self._rastrea_reconexiones = True

    def run(self) -> None:
        p = self.params
        fallos = 0
        backoff = p.backoff_inicial_s
        self._n_conexiones = 0
        self._conexion_actual = None
        while not self._parar.is_set() and not self._completo():
            antes = self._seq
            self._parser = None
            self._conexion_actual = None
            self._bytes_conexion = 0
            try:
                self._sesion()
                detalle = "el servidor cerró la conexión"
            except _Parada:
                break
            except (OSError, ErrorProtocolo) as e:
                detalle = f"{type(e).__name__}: {e}"
            if self._completo() or self._parar.is_set():
                break
            pendientes = self._parser.bytes_pendientes() if self._parser else 0
            self._evento(
                "corte",
                conexion=self._conexion_actual,
                parciales=pendientes,
                total=self._bytes_conexion,
                detalle=detalle,
            )
            if self._seq > antes:
                fallos, backoff = 0, p.backoff_inicial_s
            fallos += 1 if self._seq == antes else 0
            if fallos >= p.intentos_max:
                self.resumen.abandonada = True
                self._evento("abandono", detalle=f"{fallos} fallos seguidos")
                break
            self._evento("reintento", detalle=f"espera {backoff} s")
            self.resumen.sumar(reconexiones=1)
            if self._parar.wait(backoff):
                break
            backoff = min(backoff * 2, p.backoff_max_s)

    def _sesion(self) -> None:
        p = self.params
        t_req = perf_counter_ns()
        sock = socket.create_connection(
            (self.spec.host, self.spec.puerto), timeout=p.timeout_conexion_s
        )
        conexion = self._n_conexiones
        self._n_conexiones += 1
        self._conexion_actual = conexion
        try:
            sock.settimeout(_TICK_S)
            sock.sendall(self._peticion("keep-alive"))
            self._evento("conexion_abierta", conexion=conexion)
            parser = self._parser = ParserMJPEG("stream")
            buf = bytearray(p.recv_bytes)
            mv = memoryview(buf)
            ultimo = time.monotonic()
            while not self._completo():
                if self._parar.is_set():
                    raise _Parada
                try:
                    n = sock.recv_into(mv)
                    t_recv = perf_counter_ns()  # inmediatamente tras recv_into
                except TimeoutError:
                    if time.monotonic() - ultimo > p.timeout_inactividad_s:
                        raise TimeoutError(
                            f"sin datos durante {p.timeout_inactividad_s} s"
                        ) from None
                    continue
                ultimo = time.monotonic()
                if n == 0:
                    raise ConnectionError("el servidor cerró la conexión")
                self._bytes_conexion += n
                for f in parser.feed(mv[:n], t_recv):
                    if self._completo():
                        break
                    self._emitir(f, conexion, t_req, self._bytes_conexion)
        finally:
            self.resumen.bytes_recv_por_conexion.append(self._bytes_conexion)
            sock.close()


class LectorCapture(_LectorBase):
    """/capture: una conexión nueva (Connection: close) por muestra, sin reconexión.

    t_request_ns = instante antes de enviar la petición (tras conectar). Un fallo es
    una fila con `error`. `conexion` = seq (cada muestra abre su conexión).
    """

    def __init__(self, *args, pausa_s: float = 0.0, **kw) -> None:
        super().__init__(*args, **kw)
        self.pausa_s = pausa_s

    def run(self) -> None:
        while not self._parar.is_set() and not self._completo():
            self._muestra()
            if self.pausa_s and self._parar.wait(self.pausa_s):
                break

    def _muestra(self) -> None:
        p = self.params
        conexion = self._seq
        t_req = None
        total = 0
        sock = None
        try:
            sock = socket.create_connection(
                (self.spec.host, self.spec.puerto), timeout=p.timeout_conexion_s
            )
            sock.settimeout(_TICK_S)
            t_req = perf_counter_ns()
            sock.sendall(self._peticion("close"))
            parser = ParserMJPEG("captura")
            buf = bytearray(p.recv_bytes)
            mv = memoryview(buf)
            ultimo = time.monotonic()
            fotogramas: list[Fotograma] = []
            while not fotogramas:
                if self._parar.is_set():
                    raise _Parada
                try:
                    n = sock.recv_into(mv)
                    t_recv = perf_counter_ns()  # inmediatamente tras recv_into
                except TimeoutError:
                    if time.monotonic() - ultimo > p.timeout_inactividad_s:
                        raise TimeoutError(
                            f"sin respuesta durante {p.timeout_inactividad_s} s"
                        ) from None
                    continue
                if n == 0:
                    fotogramas = parser.fin_de_flujo()
                    if not fotogramas:
                        raise ConnectionError("conexión cerrada sin fotograma")
                    break
                ultimo = time.monotonic()
                total += n
                fotogramas = parser.feed(mv[:n], t_recv)
            self._emitir(fotogramas[0], conexion, t_req, parser.bytes_totales)
        except _Parada:
            return
        except (OSError, ErrorProtocolo) as e:
            fila = self._fila_base(conexion, t_req)
            fila["error"] = f"{type(e).__name__}: {e}"
            fila["bytes_recv_total"] = total
            self.resumen.sumar(fotogramas=1, errores=1)
            self.sink_fila(fila)
        finally:
            if sock is not None:
                self.resumen.bytes_recv_por_conexion.append(total)
                sock.close()
