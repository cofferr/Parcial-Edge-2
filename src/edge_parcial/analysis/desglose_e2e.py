"""Desglose del e2e (Tarea 1.5) y tabla del Reto experto 1.

- ESP32 `/capture`: t_request se sella DESPUÉS de conectar (docs/DISENO.md §19.2), así que
  t_request→t_first = ida de la petición (0,5 RTT) + tproc_dispositivo + vuelta del primer
  byte (0,5 RTT) + residuo. El connect (1 RTT) queda fuera de ese tramo. Red = RTT TCP de
  la Tarea 1.4 (media) y el residuo se calcula fotograma a fotograma.
- t_first→t_last (ttx): teórico (bits / v_nominal) y residuo.
- t_last→t_ready: espera en cola + decodificación (suma exacta, sin residuo).
- Las medias suman; los p95 NO (cada fila tiene su propia distribución).
Los valores se guardan sin redondear.
"""

import math

import pandas as pd

from edge_parcial.analysis import tarea_1_2_1_3 as t12
from edge_parcial.analysis.carga import Corrida
from edge_parcial.analysis.estadisticas import estadisticos
from edge_parcial.analysis.tarea_1_5 import velocidad_nominal_bps
from edge_parcial.config import Config

NAN = math.nan
COLS_DESGLOSE = ["tramo", "componente", "n", "media_ms", "p95_ms", "nota"]
COLS_RETO = ["modo", "fuente", "definicion_L", "n", "media_ms", "p50_ms", "p95_ms",
             "maximo_ms", "brecha_p95_media_ms", "Lmax_ms", "cumple"]  # fmt: skip


def ultima_utilizable(
    corridas: list[Corrida], tarea: str, fuente: str, modo: str | None = None
) -> Corrida | None:
    """Corrida 1 más reciente utilizable de la fuente (las repetidas reemplazan a las fallidas)."""
    for c in reversed(corridas):
        if (
            c.tarea == tarea
            and c.numero == 1
            and fuente in c.fuentes
            and (modo is None or c.modo == modo)
            and t12.estado_fuente(c, fuente)[0]
        ):
            return c
    return None


def _ms(serie) -> pd.Series:
    return serie.astype("float64") / 1e6


def _fila(tramo: str, componente: str, valores, nota: str = "") -> dict:
    est = estadisticos(valores)
    return {"tramo": tramo, "componente": componente, "n": est["n"],
            "media_ms": est["media"], "p95_ms": est["p95"], "nota": nota}  # fmt: skip


def desglose_esp32(c: Corrida, cfg: Config, tprop_res: pd.DataFrame) -> pd.DataFrame:
    """Desglose del e2e de la ESP32 por `/capture` (una fila por componente)."""
    df = t12.medidas(c, "esp32")
    tcp = tprop_res.set_index("fuente").loc["esp32"]
    rtt_media, rtt_p95 = float(tcp["rtt_tcp_ms_media"]), float(tcp["rtt_tcp_ms_p95"])
    if math.isnan(rtt_media):
        raise ValueError("falta el RTT por connect TCP de la ESP32 (Tarea 1.4)")
    filas = []

    arranque = _ms(df["t_first_ns"] - df["t_request_ns"])
    disp = (df["flush_us"] + df["capture_us"] + df["jpeg_us"]).astype("float64") / 1000
    filas += [
        _fila("t_request→t_first", "total medido", arranque),
        {"tramo": "t_request→t_first", "componente": "red (1 RTT TCP: 0,5 ida + 0,5 vuelta)",
         "n": int(tcp["rtt_tcp_ms_n"]), "media_ms": rtt_media, "p95_ms": rtt_p95,
         "nota": "RTT TCP de la Tarea 1.4; el connect queda fuera (t_request es posterior)"},
        _fila("t_request→t_first", "tproc_dispositivo (flush+capture+jpeg)", disp),
        _fila("t_request→t_first", "residuo", arranque - rtt_media - disp,
              "total − RTT medio − tproc_dispositivo, por fotograma"),
    ]  # fmt: skip

    v = velocidad_nominal_bps(cfg, "esp32", c.meta)
    for cobertura, d, nota in _coberturas_ttx(df):
        real = _ms(d["t_last_ns"] - d["t_first_ns"])
        teorico = d["payload_bytes"].astype("float64") * 8 / v * 1000
        filas += [
            _fila("t_first→t_last", f"ttx medido ({cobertura})", real, nota),
            _fila("t_first→t_last", f"ttx teórico ({cobertura})", teorico, "bits / v_nominal"),
            _fila("t_first→t_last", f"residuo ({cobertura})", real - teorico, "ttx medido − teórico"),
        ]  # fmt: skip

    cola = _ms(df["t_decode_ini_ns"] - df["t_last_ns"])
    deco = _ms(df["t_ready_ns"] - df["t_decode_ini_ns"])
    filas += [
        _fila("t_last→t_ready", "total medido", _ms(df["t_ready_ns"] - df["t_last_ns"])),
        _fila("t_last→t_ready", "espera en cola", cola),
        _fila("t_last→t_ready", "decodificación", deco),
        _fila("t_last→t_ready", "residuo", cola * 0, "suma exacta: cola + decodificación"),
    ]  # fmt: skip

    filas.append(_fila("e2e", "e2e medido (t_ready − t_request)", _ms(df["t_ready_ns"] - df["t_request_ns"])))  # fmt: skip
    return pd.DataFrame(filas).reindex(columns=COLS_DESGLOSE)


def arranque_droidcam(e2e: Corrida, regimen: Corrida) -> pd.DataFrame:
    """t_arranque = t_first − t_request y e2e de DroidCam, junto a la entrega en régimen
    estable de la Tarea 1.3 (ttx, entrega t_ready − t_first e interarribo)."""
    df = t12.medidas(e2e, "droidcam")
    filas = [
        _fila("e2e (1.5)", "t_arranque = t_first − t_request", _ms(df["t_first_ns"] - df["t_request_ns"])),
        _fila("e2e (1.5)", "e2e medido (t_ready − t_request)", _ms(df["t_ready_ns"] - df["t_request_ns"])),
    ]  # fmt: skip
    reg = t12.medidas(regimen, "droidcam")
    ttx, _, _ = t12.ttx_ms(reg)
    filas += [
        _fila("régimen estable (1.3)", "ttx medido (t_last − t_first)", ttx),
        _fila("régimen estable (1.3)", "entrega (t_ready − t_first)", _ms(reg["t_ready_ns"] - reg["t_first_ns"])),
        _fila("régimen estable (1.3)", "interarribo entre fotogramas", t12.interarribos_ms(t12.medidas(regimen, "droidcam", solo_validas=False), "droidcam"), "t_first[i] − t_first[i−1]"),
    ]  # fmt: skip
    return pd.DataFrame(filas).reindex(columns=COLS_DESGLOSE)


def _serie_L(c: Corrida, fuente: str) -> tuple[str, pd.Series]:
    """(definición, L por fotograma en ms). Local: read(); red: ver `tabla_reto1`."""
    df = t12.medidas(c, fuente)
    if c.tarea == "1.5" or fuente == "local":
        return "e2e: t_ready − t_request", _ms(df["t_ready_ns"] - df["t_request_ns"])
    return "régimen: t_ready − t_first", _ms(df["t_ready_ns"] - df["t_first_ns"])


def tabla_reto1(corridas: list[Corrida], lmax_ms: float) -> pd.DataFrame:
    """Reto experto 1: L por fuente y modo, con media, p50, p95, máximo y cumple (p95 ≤ Lmax).

    Aislada = e2e de la Tarea 1.5. Concurrente: no hay e2e medido, se usa la entrega en
    régimen (t_ready − t_first) de la corrida concurrente de 1.2/1.3; el local conserva
    read() (misma definición en ambos modos). Se añade la entrega en régimen aislada de
    cada fuente de red para comparar con la concurrente en igualdad de definición.
    """
    filas = []

    def agregar(modo: str, fuente: str, c: Corrida | None, etiqueta: str = "") -> None:
        base = {"modo": modo, "fuente": etiqueta or fuente}
        if c is None:
            filas.append(base | {"definicion_L": "sin corrida utilizable"})
            return
        definicion, L = _serie_L(c, fuente)
        est = estadisticos(L)
        filas.append(base | {
            "definicion_L": definicion, "n": est["n"], "media_ms": est["media"],
            "p50_ms": est["p50"], "p95_ms": est["p95"], "maximo_ms": est["maximo"],
            "brecha_p95_media_ms": est["p95"] - est["media"], "Lmax_ms": lmax_ms,
            "cumple": bool(est["p95"] <= lmax_ms),
        })  # fmt: skip

    for f in t12.ORDEN_FUENTES:
        agregar("aislada", f, ultima_utilizable(corridas, "1.5", f))
    for f in ("esp32", "droidcam"):
        agregar("aislada", f, ultima_utilizable(corridas, "1.2_1.3", f, "aislada"), f"{f} (régimen)")  # fmt: skip
    for f in t12.ORDEN_FUENTES:
        agregar(
            "concurrente", f, ultima_utilizable(corridas, "1.2_1.3", f, "concurrente")
        )
    return pd.DataFrame(filas).reindex(columns=COLS_RETO)


def _coberturas_ttx(df: pd.DataFrame) -> list[tuple[str, pd.DataFrame, str]]:
    """Las dos coberturas del ttx: todas las filas (n_recv=1 aporta ttx=0, cota inferior
    por resolución) y solo n_recv>1 (sesgada hacia arriba: descarta las entregas rápidas)."""
    mayor = df[df["n_recv"] > 1]
    return [
        ("todas", df, "ttx=0 en n_recv=1: cota inferior por resolución"),
        (
            "solo n_recv>1",
            mayor,
            f"sesgada hacia arriba: excluye {len(df) - len(mayor)} filas con n_recv=1",
        ),
    ]


def velocidad_efectiva_esp32(c: Corrida, cfg: Config) -> pd.DataFrame:
    """Velocidad efectiva = bits de la carga / suma de ttx, con las dos coberturas.

    Con todas las filas el tiempo es una cota inferior, así que la velocidad es una cota
    superior; con n_recv>1 el tiempo está sesgado hacia arriba y la velocidad hacia abajo.
    """
    df = t12.medidas(c, "esp32")
    v = velocidad_nominal_bps(cfg, "esp32", c.meta) / 1e6
    filas = []
    for cobertura, d, nota in _coberturas_ttx(df):
        seg = float((d["t_last_ns"].astype("int64") - d["t_first_ns"].astype("int64")).sum()) / 1e9  # fmt: skip
        bits = float(d["payload_bytes"].astype("int64").sum()) * 8
        ef = bits / seg / 1e6 if seg > 0 else NAN
        filas.append({"cobertura": cobertura, "n": len(d), "velocidad_efectiva_mbps": ef,
                      "razon_efectiva_nominal": ef / v, "nota": nota})  # fmt: skip
    return pd.DataFrame(filas)
