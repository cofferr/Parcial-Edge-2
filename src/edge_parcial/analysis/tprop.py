"""Resumen de la Tarea 1.4 desde tprop.csv (sin redondear).

tprop = RTT_ICMP_reposo / 2 (≥100 muestras). RTT por connect TCP: contraste. Línea base
a la puerta de enlace. d/v físico con d de la config. El RTT bajo carga se reporta
aparte y NUNCA entra en la fórmula.
"""

import math
from pathlib import Path

import pandas as pd

from edge_parcial.analysis.estadisticas import con_prefijo, estadisticos
from edge_parcial.config import Config
from edge_parcial.tprop import tprop_fisico_s

MIN_MUESTRAS = 100
SUFIJOS = ("media", "minimo", "maximo", "desviacion", "p50", "p95")


def _rtt_ms(df: pd.DataFrame, source: str, metodo: str, condicion: str) -> list[float]:
    d = df[
        (df["source"] == source)
        & (df["metodo"] == metodo)
        & (df["condicion"] == condicion)
    ]
    return [float(x) / 1e6 for x in d["rtt_ns"].dropna()]


def resumen_fuente(
    df: pd.DataFrame, source: str, distancia_m: float, v_m_s: float
) -> dict:
    icmp = estadisticos(_rtt_ms(df, source, "icmp", "reposo"))
    r: dict = {"fuente": source}
    r.update(con_prefijo(icmp, "rtt_icmp_ms"))
    # tprop = RTT/2: se aplica a cada estadístico (la división es lineal).
    for k in SUFIJOS:
        r[f"tprop_icmp_ms_{k}"] = icmp[k] / 2
    r["muestras_icmp_suficientes"] = icmp["n"] >= MIN_MUESTRAS
    r["perdidos_icmp"] = int(
        ((df["source"] == source) & (df["metodo"] == "icmp") & (df["condicion"] == "reposo") & (df["perdido"] == 1)).sum()
    )  # fmt: skip
    tcp = estadisticos(_rtt_ms(df, source, "tcp", "reposo"))
    r.update(con_prefijo(tcp, "rtt_tcp_ms"))
    r["muestras_tcp_suficientes"] = tcp["n"] >= MIN_MUESTRAS
    r["tprop_tcp_ms_media"] = tcp["media"] / 2
    carga = estadisticos(_rtt_ms(df, source, "icmp", "carga"))
    r.update(
        con_prefijo(carga, "rtt_carga_ms")
    )  # SOLO informativo, fuera de la fórmula
    r["distancia_m"] = distancia_m
    r["tprop_fisico_ns"] = tprop_fisico_s(distancia_m, v_m_s) * 1e9
    r["razon_medido_fisico"] = (
        icmp["media"] / 2 * 1e6 / r["tprop_fisico_ns"]
        if r["tprop_fisico_ns"] > 0
        else math.nan
    )
    return r


def resumen_tprop(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Una fila por fuente: gateway, esp32, droidcam y local (sin red: 0)."""
    v = cfg.v_propagacion_m_s
    filas = []
    base = estadisticos(_rtt_ms(df, "gateway", "icmp", "reposo"))
    fila_gw = {"fuente": "gateway", **con_prefijo(base, "rtt_icmp_ms")}
    for k in SUFIJOS:
        fila_gw[f"tprop_icmp_ms_{k}"] = base[k] / 2
    fila_gw["muestras_icmp_suficientes"] = base["n"] >= MIN_MUESTRAS
    filas.append(fila_gw)
    for fuente, dist in (
        ("esp32", cfg.esp32.distancia_m),
        ("droidcam", cfg.droidcam.distancia_m),
    ):
        if (df["source"] == fuente).any():
            filas.append(resumen_fuente(df, fuente, dist, v))
    filas.append(
        {
            "fuente": "local",
            "tprop_icmp_ms_media": 0.0,
            "distancia_m": cfg.local.distancia_m,
            "tprop_fisico_ns": tprop_fisico_s(cfg.local.distancia_m, v) * 1e9,
            "nota": "sin enlace de red: tprop = 0",
        }
    )
    return pd.DataFrame(filas)


def cargar_tprop(carpeta: Path | str) -> pd.DataFrame:
    return pd.read_csv(
        Path(carpeta) / "tprop.csv",
        dtype={"rtt_ns": "Int64", "perdido": "Int64", "seq": "Int64"},
    )
