"""Generador de corridas sintéticas (frames.csv + metadata.json) con valores conocidos.

Todo es determinista: sirve para probar el análisis sin hardware y sin inventar medidas.
"""

import json
from pathlib import Path

from edge_parcial.acquisition.modelo import fila_vacia
from edge_parcial.acquisition.registro import RegistroCSV

T0 = 1_000_000_000_000_000  # ~11,6 días en ns: suficientemente grande para detectar floats


def filas_red(
    run_id, source, endpoint, n, warmup=20, payload=1000, ttx_ms=4.0, periodo_ms=100.0,
    uno_cada=0, conexion_de=None, condition="aislada", decode_ms=2.0, cola_ms=0.5,
    capture_us=None, flush_us=None, jpeg_us=2000, rssi=-50, request_antes_ms=1.0, fw="T1",
    t0=T0, resp_ms=None,
):  # fmt: skip
    """Filas de una fuente de red. `uno_cada`=k pone n_recv=1 (ttx=0) en cada k-ésima fila."""
    filas = []
    for i in range(warmup + n):
        f = fila_vacia()
        t_first = t0 + int(i * periodo_ms * 1e6) + (resp_ms and int(resp_ms * 1e6) or 0)
        uno = bool(uno_cada) and (i % uno_cada == 0)
        ttx = 0 if uno else int(ttx_ms * 1e6) + (i % 3) * 1237
        t_last = t_first + ttx
        f.update(
            run_id=run_id, source=source, endpoint=endpoint, condition=condition, seq=i,
            warmup=int(i < warmup), conexion=(conexion_de(i) if conexion_de else 0),
            t_request_ns=t0 + int(i * periodo_ms * 1e6) - int(request_antes_ms * 1e6)
            if endpoint == "/capture" or resp_ms
            else t0 - int(request_antes_ms * 1e6),
            t_first_ns=t_first, t_last_ns=t_last, t_decode_ini_ns=t_last + int(cola_ms * 1e6),
            t_ready_ns=t_last + int((cola_ms + decode_ms) * 1e6),
            n_recv=1 if uno else 3, payload_bytes=payload + (i % 5), header_bytes=60,
            jpeg_valid=1, width=320, height=240, capture_us=capture_us, flush_us=flush_us,
            jpeg_us=jpeg_us if source == "esp32" else None,
            rssi_dbm=rssi if source == "esp32" else None,
            fw=fw if source == "esp32" else None, bytes_recv_total=(i + 1) * payload,
            descartado=0,
        )  # fmt: skip
        filas.append(f)
    return filas


def filas_local(run_id, n, warmup=20, raw=6_220_800, jpeg=90_000, lectura_ms=33.0,
                condition="aislada", t0=T0):  # fmt: skip
    filas = []
    for i in range(warmup + n):
        f = fila_vacia()
        t_req = t0 + int(i * lectura_ms * 1e6)
        t_ready = t_req + int(lectura_ms * 1e6)
        f.update(
            run_id=run_id, source="local", endpoint="cv2.read", condition=condition, seq=i,
            warmup=int(i < warmup), conexion=0, t_request_ns=t_req, t_ready_ns=t_ready,
            t_encode_ini_ns=t_ready + 1000, t_encode_fin_ns=t_ready + 1000 + 8_000_000,
            raw_bytes=raw, payload_bytes=jpeg + (i % 7), jpeg_valid=1, width=1920,
            height=1080, descartado=0,
        )  # fmt: skip
        filas.append(f)
    return filas


def escribir_corrida(
    raw: Path, run_id: str, filas: list[dict], *, tarea="1.2_1.3", modo="aislada", corrida=1,
    fuentes=None, validez=None, lectores=None, extra_meta=None,
):  # fmt: skip
    """Escribe data/raw/<run_id>/{frames.csv, metadata.json}."""
    fuentes = fuentes or sorted(
        {f["source"] for f in filas}, key=["local", "esp32", "droidcam"].index
    )
    carpeta = Path(raw) / run_id
    with RegistroCSV(carpeta) as reg:
        for f in filas:
            reg.fila(f)
    meta = {
        "run_id": run_id,
        "fuentes_usadas": fuentes,
        "contexto": {
            "tarea": tarea,
            "modo": modo,
            "corrida": corrida,
            "fuente": fuentes[0] if modo == "aislada" else "todas",
        },
        "valida": True,
        "motivos_invalida": [],
        "validez_por_fuente": validez
        or {f: {"valida": True, "motivos": []} for f in fuentes},
        "lectores": lectores or {f: {"con_reconexiones": False} for f in fuentes},
    }
    meta.update(extra_meta or {})
    (carpeta / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return carpeta
