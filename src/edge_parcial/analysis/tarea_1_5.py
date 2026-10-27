"""Tarea 1.5: latencia teórica L = ttx + tprop + tproc frente al e2e medido; ancho de banda.

- ttx teórico = bits de la carga / velocidad nominal. Nominal: ESP32 desde la config (con su
  fuente citada); DroidCam desde `tasa_transmision_mbps` del Wi-Fi del Mac en la metadata de
  la corrida (media de inicio y cierre). La velocidad efectiva solo explica la brecha.
- tprop = RTT_ICMP_reposo / 2 (Tarea 1.4). El RTT bajo carga no entra.
- tproc = dispositivo + host. Dispositivo (solo ESP32): /capture = flush + capture + jpeg;
  /stream = capture + jpeg ("sin espera de sensor"). Host = decodificación
  (t_ready - t_decode_ini); la espera en cola se reporta aparte y NO entra.
- e2e medido = t_ready - t_request. Local: no hay modelo de red; se reporta el e2e medido
  (read()) y L teórico queda vacío.
- Discrepancia = (L medido - L teórico) / L teórico. El e2e medido incluye el establecimiento
  de la conexión y la petición HTTP, que el modelo no contempla.
Los valores se guardan sin redondear; el redondeo es solo de presentación (LaTeX).
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd

from edge_parcial.analysis import tarea_1_2_1_3 as t12
from edge_parcial.analysis.carga import Corrida, cargar_corridas
from edge_parcial.analysis.tablas import escribir_tabla
from edge_parcial.analysis.tprop import elegir_tprop, tabla_tprop
from edge_parcial.config import Config

NAN = math.nan


def tasa_wifi_bps(meta: dict) -> float:
    """Media de la tasa de transmisión del Wi-Fi del Mac al inicio y al cierre (bps)."""
    tasas = [
        meta.get(k, {}).get("tasa_transmision_mbps")
        for k in ("wifi_mac_inicio", "wifi_mac_fin")
    ]
    tasas = [float(t) for t in tasas if t]
    return float(np.mean(tasas)) * 1e6 if tasas else NAN


def velocidad_nominal_bps(cfg: Config, fuente: str, meta: dict) -> float:
    if fuente == "esp32":
        return float(cfg.esp32.velocidad_nominal_bps or NAN)
    if fuente == "droidcam":
        return tasa_wifi_bps(meta)
    return NAN


def _media_mediana(serie) -> tuple[float, float]:
    x = np.asarray([float(v) for v in serie if v is not None and not pd.isna(v)])
    return (float(x.mean()), float(np.median(x))) if x.size else (NAN, NAN)


def latencia_fuente(
    c: Corrida, fuente: str, cfg: Config, tprop_res: pd.DataFrame | None
) -> dict:
    ok, motivo = t12.estado_fuente(c, fuente)
    r: dict = {
        "fuente": fuente, "run_id": c.run_id, "corrida": c.numero,
        "metodo_e2e": c.contexto.get("metodo_e2e"),
        "utilizable": ok, "estado": "ok" if ok else f"EXCLUIDA: {motivo}",
    }  # fmt: skip
    if not ok:
        return r
    df = t12.medidas(c, fuente)
    r["n"] = len(df)
    e2e = (df["t_ready_ns"] - df["t_request_ns"]) / 1e6
    r["L_medido_ms"], r["L_medido_p50_ms"] = _media_mediana(e2e)
    if fuente == "local":
        r["nota"] = "sin modelo de red: e2e = read() con la cámara abierta"
        return r
    r["payload_media_B"], payload_p50 = _media_mediana(df["payload_bytes"])
    v = velocidad_nominal_bps(cfg, fuente, c.meta)
    r["v_nominal_mbps"] = v / 1e6
    ttx = r["payload_media_B"] * 8 / v * 1000
    ttx_p50 = payload_p50 * 8 / v * 1000
    r["ttx_teorico_ms"] = ttx
    # tprop
    tp, tp50 = NAN, NAN
    if tprop_res is not None and fuente in set(tprop_res["fuente"]):
        fila = tprop_res.set_index("fuente").loc[fuente]
        tp, tp50 = float(fila["tprop_icmp_ms_media"]), float(fila["tprop_icmp_ms_p50"])
    r["tprop_ms"] = tp
    # tproc dispositivo (solo ESP32; DroidCam no expone cabeceras)
    disp, disp50 = 0.0, 0.0
    if fuente == "esp32":
        capture = (df["endpoint"] == "/capture").all()
        suma = df["capture_us"] + df["jpeg_us"] + (df["flush_us"] if capture else 0)
        disp, disp50 = (x / 1000 for x in _media_mediana(suma))
        r["tproc_dispositivo_etiqueta"] = (
            "flush+capture+jpeg" if capture else "capture+jpeg (sin espera de sensor)"
        )
    r["tproc_dispositivo_ms"] = disp
    deco = (df["t_ready_ns"] - df["t_decode_ini_ns"]) / 1e6
    r["tproc_host_ms"], deco50 = _media_mediana(deco)
    r["espera_cola_ms"] = _media_mediana(
        (df["t_decode_ini_ns"] - df["t_last_ns"]) / 1e6
    )[0]
    r["L_teorico_ms"] = ttx + tp + disp + r["tproc_host_ms"]
    r["L_teorico_p50_ms"] = ttx_p50 + tp50 + disp50 + deco50
    r["discrepancia_ms"] = r["L_medido_ms"] - r["L_teorico_ms"]
    r["discrepancia_pct"] = 100 * r["discrepancia_ms"] / r["L_teorico_ms"]
    r["discrepancia_p50_pct"] = (
        100 * (r["L_medido_p50_ms"] - r["L_teorico_p50_ms"]) / r["L_teorico_p50_ms"]
    )
    if math.isnan(r["L_teorico_ms"]):
        r["nota"] = "L teórico incompleto (falta tprop o velocidad nominal)"
    return r


def tabla_latencia(
    corridas: list[Corrida],
    cfg: Config,
    tprop_res: pd.DataFrame | None,
    tprop_run: str | None,
) -> pd.DataFrame:
    filas = []
    for c in corridas:
        if c.tarea != "1.5" or c.numero != 1:  # oficial = corrida 1
            continue
        for f in t12.ORDEN_FUENTES:
            if f in c.fuentes:
                r = latencia_fuente(c, f, cfg, tprop_res)
                r["tprop_run_id"] = tprop_run
                filas.append(r)
    cols = ["fuente", "run_id", "metodo_e2e", "n", "payload_media_B", "v_nominal_mbps",
            "ttx_teorico_ms", "tprop_ms", "tproc_dispositivo_ms", "tproc_host_ms",
            "L_teorico_ms", "L_medido_ms", "discrepancia_ms", "discrepancia_pct",
            "L_teorico_p50_ms", "L_medido_p50_ms", "discrepancia_p50_pct", "espera_cola_ms",
            "tprop_run_id", "estado", "nota"]  # fmt: skip
    return pd.DataFrame(filas).reindex(columns=cols)


def tabla_brecha(
    res12: pd.DataFrame, corridas: list[Corrida], cfg: Config
) -> pd.DataFrame:
    """Velocidad nominal vs efectiva (1.2/1.3, corrida 1): solo explica la brecha."""
    por_run = {c.run_id: c for c in corridas}
    filas = []
    for _, r in res12[
        (res12["corrida"] == 1) & (res12["fuente"] != "local")
    ].iterrows():
        if not r["utilizable"]:
            filas.append(
                {"modo": r["modo"], "fuente": r["fuente"], "estado": r["estado"]}
            )
            continue
        v = velocidad_nominal_bps(cfg, r["fuente"], por_run[r["run_id"]].meta)
        ef = r["velocidad_efectiva_mbps"]
        teo = r["payload_media"] * 8 / v * 1000
        filas.append(
            {
                "modo": r["modo"], "fuente": r["fuente"], "v_nominal_mbps": v / 1e6,
                "v_efectiva_mbps": ef, "razon_efectiva_nominal": ef / (v / 1e6),
                "ttx_real_ms_media": r["ttx_ms_media"], "ttx_teorico_ms": teo,
                "estado": r["estado"],
            }
        )  # fmt: skip
    cols = ["modo", "fuente", "v_nominal_mbps", "v_efectiva_mbps", "razon_efectiva_nominal",
            "ttx_real_ms_media", "ttx_teorico_ms", "estado"]  # fmt: skip
    return pd.DataFrame(filas).reindex(columns=cols)


def tabla_ancho_banda(res12: pd.DataFrame) -> pd.DataFrame:
    """Ancho de banda por fuente = tamaño medio × 8 × FPS medio (corrida 1) y total por modo."""
    filas = []
    for modo, g in res12[res12["corrida"] == 1].groupby("modo"):
        total = 0.0
        for _, r in g.iterrows():
            if not r["utilizable"]:
                filas.append(
                    {"modo": modo, "fuente": r["fuente"], "estado": r["estado"]}
                )
                continue
            tipos = (
                [
                    ("JPEG q50 (referencia)", r["payload_media"]),
                    ("bruto", r["raw_media"]),
                ]
                if r["fuente"] == "local"
                else [("carga JPEG", r["payload_media"])]
            )
            for tipo, tam in tipos:
                bps = tam * 8 * r["fps_medio"]
                filas.append(
                    {
                        "modo": modo, "fuente": r["fuente"], "tipo": tipo,
                        "tamano_medio_B": tam, "fps_medio": r["fps_medio"],
                        "ancho_banda_mbps": bps / 1e6, "estado": r["estado"],
                    }
                )  # fmt: skip
                if tipo != "bruto":
                    total += bps
        filas.append({"modo": modo, "fuente": "TOTAL", "tipo": "JPEG (sin bruto)", "ancho_banda_mbps": total / 1e6, "estado": "ok"})  # fmt: skip
    cols = [
        "modo",
        "fuente",
        "tipo",
        "tamano_medio_B",
        "fps_medio",
        "ancho_banda_mbps",
        "estado",
    ]
    return pd.DataFrame(filas).reindex(columns=cols)


def generar_todo(raw: Path | str, salida: Path | str, cfg: Config) -> dict[str, Path]:
    """Genera las tablas 1.2/1.3, 1.4 y 1.5 (CSV sin redondear + LaTeX redondeado)."""
    raw, salida = Path(raw), Path(salida)
    corridas = cargar_corridas(raw)
    escritas = dict(
        t12.generar_tablas([c for c in corridas if c.tarea == t12.TAREA], salida)
    )
    res12 = t12.resumenes(corridas)

    tprop_res, tprop_run = elegir_tprop(raw, cfg)
    if tprop_res is not None:
        t = tabla_tprop(tprop_res)
        escribir_tabla(
            t, salida / "t1_4_tprop", caption=f"Tiempo de propagación (ms), corrida {tprop_run}; el RTT bajo carga va aparte",
            label="tab:t1_4_tprop", decimales={"tprop_fisico_ns": 2, "muestras_icmp_suficientes": 0, **dict.fromkeys(t.columns, 3)},
        )  # fmt: skip
        escritas["t1_4_tprop"] = salida / "t1_4_tprop"

    if any(c.tarea == "1.5" for c in corridas):
        lat = tabla_latencia(corridas, cfg, tprop_res, tprop_run)
        escribir_tabla(
            lat.drop(columns=["run_id", "tprop_run_id", "metodo_e2e", "nota"]),
            salida / "t1_5_latencia",
            caption="Latencia teórica L = ttx + tprop + tproc frente al e2e medido (ms), corrida 1",
            label="tab:t1_5_latencia", decimales=3,
        )  # fmt: skip
        # El CSV completo (con run_id y notas) se conserva aparte, sin redondear.
        lat.to_csv(salida / "t1_5_latencia_completa.csv", index=False)
        escritas["t1_5_latencia"] = salida / "t1_5_latencia"
    if not res12.empty:
        br = tabla_brecha(res12, corridas, cfg)
        escribir_tabla(br, salida / "t1_5_brecha_velocidad", caption="Velocidad nominal frente a efectiva (solo explica la brecha)", label="tab:t1_5_brecha", decimales=3)  # fmt: skip
        ab = tabla_ancho_banda(res12)
        escribir_tabla(ab, salida / "t1_5_ancho_banda", caption="Ancho de banda por fuente (Mbps), corrida 1", label="tab:t1_5_ancho_banda", decimales=3)  # fmt: skip
        escritas["t1_5_brecha_velocidad"] = salida / "t1_5_brecha_velocidad"
        escritas["t1_5_ancho_banda"] = salida / "t1_5_ancho_banda"
    return escritas
