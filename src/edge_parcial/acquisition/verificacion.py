"""Resumen de un frames.csv para la verificación manual del lector."""

import csv
from pathlib import Path

import numpy as np


def _num(valor: str) -> int | None:
    return int(valor) if valor not in ("", None) else None


def _pct(valores: list, q: float) -> float | None:
    return float(np.percentile(valores, q)) if valores else None


def resumir_frames(ruta: Path | str) -> dict:
    """Estadísticas de las filas sin warmup (las de warmup solo se cuentan).

    Tiempos en ms. Los inter-arribos solo se toman dentro de una misma conexión.
    """
    with open(ruta, newline="", encoding="utf-8") as f:
        todas = list(csv.DictReader(f))
    warmup = [r for r in todas if r["warmup"] == "1"]
    filas = [r for r in todas if r["warmup"] != "1"]
    con_error = [r for r in filas if r["error"]]
    ok = [r for r in filas if r["t_first_ns"] and r["t_last_ns"]]

    n_recv_1 = sum(1 for r in ok if r["n_recv"] == "1")
    ttx = [
        (int(r["t_last_ns"]) - int(r["t_first_ns"])) / 1e6
        for r in ok
        if r["n_recv"] != "1"
    ]
    cola, deco, respuesta = [], [], []
    for r in ok:
        if r["t_decode_ini_ns"]:
            cola.append((int(r["t_decode_ini_ns"]) - int(r["t_last_ns"])) / 1e6)
        if r["t_decode_ini_ns"] and r["t_ready_ns"]:
            deco.append((int(r["t_ready_ns"]) - int(r["t_decode_ini_ns"])) / 1e6)
        if r["t_request_ns"]:
            respuesta.append((int(r["t_first_ns"]) - int(r["t_request_ns"])) / 1e6)

    interarribos = []
    previo = None
    for r in ok:
        if previo is not None and previo["conexion"] == r["conexion"]:
            interarribos.append(
                (int(r["t_first_ns"]) - int(previo["t_first_ns"])) / 1e6
            )
        previo = r

    def serie(col: str) -> list[int]:
        return [v for r in ok if (v := _num(r[col])) is not None]

    # Reconexión dentro de las filas medidas (solo /stream y /video; en /capture cada
    # muestra abre su conexión y `conexion` = seq, así que no aplica).
    reconecta = {r["conexion"] for r in filas if r["endpoint"] != "/capture"}
    return {
        "con_reconexiones": len(reconecta) > 1,
        "filas_total": len(todas),
        "filas_warmup": len(warmup),
        "filas_medidas": len(filas),
        "filas_con_error": len(con_error),
        "descartadas": sum(1 for r in filas if r["descartado"] == "1"),
        "n_recv_1": n_recv_1,
        "pct_n_recv_1": 100 * n_recv_1 / len(ok) if ok else None,
        "ttx_ms_p50": _pct(ttx, 50),
        "ttx_ms_p95": _pct(ttx, 95),
        "ttx_filas_validas": len(ttx),
        "fps_medio": 1000 / float(np.mean(interarribos)) if interarribos else None,
        "interarribo_ms_p50": _pct(interarribos, 50),
        "interarribo_ms_p95": _pct(interarribos, 95),
        "interarribo_ms_max": max(interarribos) if interarribos else None,
        "huecos_mayores_1s": sum(1 for x in interarribos if x > 1000),
        "payload_bytes_medio": float(np.mean(serie("payload_bytes")))
        if serie("payload_bytes")
        else None,
        "respuesta_ms_p50": _pct(respuesta, 50),
        "espera_cola_ms_p50": _pct(cola, 50),
        "decodificacion_ms_p50": _pct(deco, 50),
        "capture_us_p50": _pct(serie("capture_us"), 50),
        "flush_us_p50": _pct(serie("flush_us"), 50),
        "jpeg_us_p50": _pct(serie("jpeg_us"), 50),
        "rssi_dbm_p50": _pct(serie("rssi_dbm"), 50),
        "resoluciones": sorted(
            {f"{r['width']}x{r['height']}" for r in ok if r["width"]}
        ),
    }
