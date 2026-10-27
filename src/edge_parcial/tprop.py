"""Tarea 1.4: tiempo de propagación (tprop).

- RTT ICMP en reposo con el `ping` del sistema (≥100 muestras); tprop = RTT / 2.
- RTT por connect TCP (≥100 muestras) como contraste.
- Línea base: RTT ICMP a la puerta de enlace.
- d/v físico con d de la config (< 1 m).
- RTT bajo carga (con la fuente transmitiendo): se reporta APARTE; nunca entra a la fórmula.

macOS (`man ping`): `-i wait` admite fracciones, pero solo el superusuario puede usar
menos de 0,002 s; se usa 0,2 s por defecto para no saturar a la ESP32-CAM. `-W` es en ms.
"""

import csv
import queue
import re
import socket
import subprocess
import threading
import time
from pathlib import Path
from time import perf_counter_ns

from edge_parcial import metadata
from edge_parcial.acquisition.lector_red import (
    LectorStream,
    spec_droidcam,
    spec_esp32_stream,
)
from edge_parcial.config import Config

TAREA = "1.4"
COLUMNAS = ["run_id", "source", "metodo", "condicion", "host", "puerto", "seq", "rtt_ns", "perdido", "error"]  # fmt: skip
_RE_RESPUESTA = re.compile(r"icmp_seq=(\d+).*?time=([0-9.]+) ms")
_RE_TIMEOUT = re.compile(r"Request timeout for icmp_seq (\d+)")


def ejecutor_sistema(cmd: list[str], timeout: float) -> tuple[int, str]:
    r = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    )
    return r.returncode, r.stdout


def parsear_ping(salida: str, n: int) -> list[int | None]:
    """RTT en ns por secuencia (0..n-1); None si se perdió. ping imprime µs (3 decimales ms)."""
    muestras: list[int | None] = [None] * n
    for linea in salida.splitlines():
        m = _RE_RESPUESTA.search(linea)
        if m and "DUP" not in linea:
            seq = int(m.group(1))
            if 0 <= seq < n and muestras[seq] is None:
                muestras[seq] = round(float(m.group(2)) * 1e6)
    return muestras


def ejecutar_ping(
    host: str,
    n: int,
    intervalo_s: float = 0.2,
    espera_ms: int = 1000,
    ejecutor=ejecutor_sistema,
) -> tuple[list[int | None], str]:
    """Devuelve (RTT en ns por muestra, salida cruda del ping)."""
    cmd = ["ping", "-c", str(n), "-i", str(intervalo_s), "-W", str(espera_ms), host]
    _, salida = ejecutor(cmd, n * (intervalo_s + espera_ms / 1000) + 15)
    return parsear_ping(salida, n), salida


def rtt_tcp(
    host: str, puerto: int, n: int, pausa_s: float = 0.05, timeout_s: float = 2.0
) -> list[tuple[int | None, str | None]]:
    """RTT por connect TCP en ns (SYN -> SYN/ACK); (None, error) si falla."""
    muestras = []
    for _ in range(n):
        t0 = perf_counter_ns()
        try:
            s = socket.create_connection((host, puerto), timeout=timeout_s)
            dt = perf_counter_ns() - t0
            s.close()
            muestras.append((dt, None))
        except OSError as e:
            muestras.append((None, f"{type(e).__name__}: {e}"))
        time.sleep(pausa_s)
    return muestras


def tprop_fisico_s(distancia_m: float, v_m_s: float) -> float:
    """Retardo de propagación físico d / v."""
    return distancia_m / v_m_s


def _filas(run_id, source, metodo, condicion, host, puerto, muestras):
    for i, m in enumerate(muestras):
        rtt, error = m if isinstance(m, tuple) else (m, None)
        yield {
            "run_id": run_id, "source": source, "metodo": metodo, "condicion": condicion,
            "host": host, "puerto": puerto, "seq": i, "rtt_ns": rtt,
            "perdido": int(rtt is None), "error": error,
        }  # fmt: skip


class _Carga:
    """Mantiene la fuente transmitiendo (LectorStream + consumidor nulo) durante el contexto."""

    def __init__(self, cfg: Config, fuente: str, run_id: str):
        spec = spec_esp32_stream(cfg) if fuente == "esp32" else spec_droidcam(cfg)
        self.cola: queue.Queue = queue.Queue(maxsize=cfg.lector.cola_max)
        self.lector = LectorStream(
            spec,
            cfg.lector,
            run_id,
            "carga",
            None,
            self.cola,
            lambda f: None,
            lambda e: None,
            None,
        )
        self._fin = threading.Event()
        self._drenaje = threading.Thread(target=self._drenar, daemon=True)

    def _drenar(self):
        while not self._fin.is_set():
            try:
                self.cola.get(timeout=0.1)
            except queue.Empty:
                pass

    def __enter__(self):
        self._drenaje.start()
        self.lector.start()
        return self

    def esperar_flujo(self, timeout_s: float = 5.0) -> bool:
        """Espera a que lleguen fotogramas (la carga está activa)."""
        fin = time.monotonic() + timeout_s
        while time.monotonic() < fin:
            if self.lector.resumen.fotogramas > 0:
                return True
            time.sleep(0.05)
        return False

    def __exit__(self, *a):
        self.lector.detener()
        self.lector.join(10)
        self._fin.set()
        self._drenaje.join(2)


def medir_tprop(
    cfg: Config,
    run_id: str,
    dir_raw: Path,
    *,
    fuentes: tuple[str, ...] = ("esp32", "droidcam"),
    n: int = 100,
    intervalo_s: float = 0.2,
    pausa_tcp_s: float = 0.05,
    carga: bool = False,
    ejecutor=ejecutor_sistema,
    log=print,
    cpu_s: float = 2.0,
) -> dict:
    """Mide tprop de las fuentes de red y la línea base a la puerta de enlace.

    Con `carga`, repite el RTT ICMP con la fuente transmitiendo (se guarda aparte).
    La ESP32-CAM debe tener el stream cerrado al empezar (y /status se consulta así).
    """
    usadas = tuple(f for f in fuentes if f != "local")
    meta = metadata.recolectar_metadata(
        cfg, run_id, fuentes=usadas, cpu_duracion_s=cpu_s, contexto={"tarea": TAREA, "n": n, "fuentes": list(fuentes)}
    )  # fmt: skip
    destinos = {
        "esp32": (cfg.esp32.ip, cfg.esp32.puerto),
        "droidcam": (cfg.droidcam.ip, cfg.droidcam.puerto),
    }
    filas: list[dict] = []
    crudo: dict[str, str] = {}

    log(f"gateway {cfg.gateway_ip}: ICMP en reposo ({n} muestras)")
    rtts, salida = ejecutar_ping(cfg.gateway_ip, n, intervalo_s, ejecutor=ejecutor)
    crudo["gateway_icmp"] = salida
    filas += _filas(run_id, "gateway", "icmp", "reposo", cfg.gateway_ip, None, rtts)
    for f in usadas:
        host, puerto = destinos[f]
        log(f"{f} {host}: ICMP en reposo ({n} muestras)")
        rtts, salida = ejecutar_ping(host, n, intervalo_s, ejecutor=ejecutor)
        crudo[f"{f}_icmp"] = salida
        filas += _filas(run_id, f, "icmp", "reposo", host, None, rtts)
        log(f"{f} {host}:{puerto}: connect TCP ({n} muestras)")
        filas += _filas(
            run_id,
            f,
            "tcp",
            "reposo",
            host,
            puerto,
            rtt_tcp(host, puerto, n, pausa_tcp_s),
        )
    if carga:
        for f in usadas:
            host, _ = destinos[f]
            log(f"{f}: ICMP bajo carga (stream activo; se reporta aparte)")
            with _Carga(cfg, f, run_id) as c:
                activo = c.esperar_flujo()
                rtts, salida = ejecutar_ping(host, n, intervalo_s, ejecutor=ejecutor)
            crudo[f"{f}_icmp_carga"] = salida
            if not activo:
                meta["validez_por_fuente"][f]["motivos"].append(
                    "la carga no llegó a transmitir: RTT bajo carga no representativo"
                )
                meta["validez_por_fuente"][f]["valida"] = False
            filas += _filas(run_id, f, "icmp", "carga", host, None, rtts)

    carpeta = Path(dir_raw) / run_id
    carpeta.mkdir(parents=True, exist_ok=True)
    with open(carpeta / "tprop.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, COLUMNAS)
        w.writeheader()
        w.writerows(filas)
    for nombre, texto in crudo.items():
        (carpeta / f"ping_{nombre}.txt").write_text(texto, encoding="utf-8")
    meta["distancias_m"] = {"esp32": cfg.esp32.distancia_m, "droidcam": cfg.droidcam.distancia_m, "local": cfg.local.distancia_m}  # fmt: skip
    meta["v_propagacion_m_s"] = cfg.v_propagacion_m_s
    metadata._validar(meta)
    metadata.cerrar_metadata(meta, cfg)
    metadata.escribir_metadata(meta, dir_raw)
    return meta
