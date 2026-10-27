"""Tarea 1.6: ahorro de ancho de banda del filtro por diferencia (sobre una grabación guiada).

Definiciones (docs/DISENO.md §22):
- f = fracción TRANSMITIDA (por fotogramas y por bytes); ahorro = (1 - f).
- Se clasifica cada fotograma por el segmento en el que cae `t_last_ns` (red) o
  `t_ready_ns` (local), descartando `guarda_s` tras cada límite de segmento.
- T_pix y T_area se calibran SOLO con el segmento de calibración (escena estática);
  f_estático y f_actividad se miden con los ciclos (datos independientes de la calibración).
- S̄ = tamaño medio del JPEG, FPS = fotogramas / duración de la grabación,
  D = S̄ × FPS × 2 592 000 s (GB decimales), A = (1 - f) × D.
- f(p) = p·f_actividad + (1 - p)·f_estático para p ∈ {1 %, 5 %, 25 %} y la mezcla real
  p_real = tiempo de actividad / tiempo de ciclos.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from edge_parcial import filtro
from edge_parcial.analysis.carga import leer_frames
from edge_parcial.analysis.tablas import escribir_tabla

SEGUNDOS_30_DIAS = 2_592_000
PROPORCIONES = (0.01, 0.05, 0.25)
MAX_ESTATICOS_TX = 0.01
ORDEN_FUENTES = ("local", "esp32", "droidcam")


class ErrorGrabacion(Exception):
    """La grabación no permite calcular (sin segmentos, sin calibración, etc.)."""


@dataclass
class Secuencia:
    """Fotogramas válidos de una fuente, en orden temporal."""

    fuente: str
    t_ns: np.ndarray
    bytes_: np.ndarray
    tipo: list[str]
    grises: list[np.ndarray]


def _t_evento(df: pd.DataFrame, fuente: str) -> pd.Series:
    return df["t_ready_ns" if fuente == "local" else "t_last_ns"]


def clasificar(t_ns: int, segmentos: pd.DataFrame, guarda_s: float) -> str:
    g = int(guarda_s * 1e9)
    for s in segmentos.itertuples():
        if s.t_ini_ns <= t_ns < s.t_fin_ns:
            return s.tipo if t_ns >= s.t_ini_ns + g else "transicion"
    return "fuera"


def cargar_secuencia(
    carpeta: Path,
    fuente: str,
    frames: pd.DataFrame,
    segmentos: pd.DataFrame,
    guarda_s: float,
) -> Secuencia:
    df = frames[(frames["source"] == fuente) & (frames["warmup"] == 0)]
    df = df[df["error"].isna() & (df["jpeg_valid"] == 1) & (df["descartado"] == 0)]
    df = (
        df.assign(t_evento=_t_evento(df, fuente))
        .dropna(subset=["t_evento"])
        .sort_values("t_evento")
    )
    t, b, tipos, grises = [], [], [], []
    for r in df.itertuples():
        ruta = carpeta / fuente / f"{int(r.seq):06d}.jpg"
        img = cv2.imread(str(ruta), cv2.IMREAD_GRAYSCALE) if ruta.exists() else None
        if img is None:  # sin archivo no hay filtro posible: se omite, no se inventa
            continue
        t.append(int(r.t_evento))
        b.append(int(r.payload_bytes))
        tipos.append(clasificar(int(r.t_evento), segmentos, guarda_s))
        grises.append(filtro.preparar(img))
    return Secuencia(
        fuente, np.array(t, dtype=np.int64), np.array(b, dtype=np.int64), tipos, grises
    )


def metricas_tipo(seq: Secuencia, mascara: np.ndarray, tipo: str) -> dict:
    idx = np.array([t == tipo for t in seq.tipo], dtype=bool)
    n, n_tx = int(idx.sum()), int((idx & mascara).sum())
    by, by_tx = int(seq.bytes_[idx].sum()), int(seq.bytes_[idx & mascara].sum())
    return {
        "tipo": tipo, "n": n, "n_tx": n_tx, "bytes": by, "bytes_tx": by_tx,
        "f_frames": n_tx / n if n else np.nan, "f_bytes": by_tx / by if by else np.nan,
    }  # fmt: skip


def duracion_tipo(segmentos: pd.DataFrame, tipo: str, guarda_s: float) -> float:
    """Segundos de segmentos `tipo` (sin la guarda inicial de cada uno)."""
    s = segmentos[segmentos["tipo"] == tipo]
    return float(((s["t_fin_ns"] - s["t_ini_ns"]) / 1e9 - guarda_s).clip(lower=0).sum())


def analizar_fuente(seq: Secuencia, segmentos: pd.DataFrame, guarda_s: float) -> dict:
    """Calibra, filtra y calcula f, D y A para una fuente."""
    calib = [g for g, t in zip(seq.grises, seq.tipo, strict=True) if t == "calibracion"]
    if len(calib) < 10:
        raise ErrorGrabacion(
            f"{seq.fuente}: {len(calib)} fotogramas de calibración (<10)"
        )
    t_pix = filtro.calibrar_t_pix(calib)
    t_area, _ = filtro.elegir_t_area(calib, t_pix, MAX_ESTATICOS_TX)
    mascara = filtro.simular(seq.grises, t_pix, t_area)
    est, act = (metricas_tipo(seq, mascara, t) for t in ("estatico", "actividad"))
    if est["n"] == 0 or act["n"] == 0:
        raise ErrorGrabacion(
            f"{seq.fuente}: faltan fotogramas estáticos o de actividad"
        )
    ciclos = np.array([t in ("estatico", "actividad") for t in seq.tipo])
    s_medio = float(seq.bytes_[ciclos].mean())
    dur = (seq.t_ns.max() - seq.t_ns.min()) / 1e9
    fps = (len(seq.t_ns) - 1) / dur
    d_gb = s_medio * fps * SEGUNDOS_30_DIAS / 1e9
    t_est = duracion_tipo(segmentos, "estatico", guarda_s)
    t_act = duracion_tipo(segmentos, "actividad", guarda_s)
    p_real = t_act / (t_act + t_est)
    return {
        "fuente": seq.fuente, "t_pix": t_pix, "t_area": t_area, "n_calibracion": len(calib),
        "estatico": est, "actividad": act, "s_medio_bytes": s_medio, "fps": fps,
        "d_gb": d_gb, "p_real": p_real, "mascara": mascara,
    }  # fmt: skip


def f_de_p(res: dict, p: float, clave: str) -> float:
    return p * res["actividad"][clave] + (1 - p) * res["estatico"][clave]


def barrido(seq: Secuencia, t_pix: float, candidatos: list[float]) -> pd.DataFrame:
    """f frente a T_area para estáticos y actividad (figura y tabla de sensibilidad)."""
    filas = []
    for t_area in candidatos:
        m = filtro.simular(seq.grises, t_pix, t_area)
        e, a = metricas_tipo(seq, m, "estatico"), metricas_tipo(seq, m, "actividad")
        filas.append(
            {
                "fuente": seq.fuente,
                "t_area": t_area,
                "f_frames_estatico": e["f_frames"],
                "f_frames_actividad": a["f_frames"],
                "f_bytes_estatico": e["f_bytes"],
                "f_bytes_actividad": a["f_bytes"],
            }
        )
    return pd.DataFrame(filas)


def tablas(resultados: list[dict]) -> dict[str, tuple[pd.DataFrame, str, dict]]:
    calib = pd.DataFrame(
        [
            {"fuente": r["fuente"], "n_calibracion": r["n_calibracion"], "t_pix": r["t_pix"],
             "t_area": r["t_area"], "estaticos_tx_pct_ciclos": 100 * r["estatico"]["f_frames"]}
            for r in resultados
        ]
    )  # fmt: skip
    f_filas = []
    for r in resultados:
        for t in ("estatico", "actividad"):
            m = r[t]
            f_filas.append({"fuente": r["fuente"], **{k: m[k] for k in ("tipo", "n", "n_tx", "f_frames", "bytes", "bytes_tx", "f_bytes")}})  # fmt: skip
    ahorro = []
    for r in resultados:
        base = {"fuente": r["fuente"], "s_medio_bytes": r["s_medio_bytes"], "fps": r["fps"], "d_gb": r["d_gb"]}  # fmt: skip
        for rotulo, p in [
            ("1 %", 0.01),
            ("5 %", 0.05),
            ("25 %", 0.25),
            ("real", r["p_real"]),
        ]:
            f = f_de_p(r, p, "f_bytes")
            ahorro.append({**base, "p": rotulo, "p_valor": p, "f_bytes": f,
                           "f_frames": f_de_p(r, p, "f_frames"), "a_gb": (1 - f) * r["d_gb"]})  # fmt: skip
    ahorro_df = pd.DataFrame(ahorro)
    total = []
    for rotulo in ahorro_df["p"].unique():
        g = ahorro_df[ahorro_df["p"] == rotulo]
        d, a = g["d_gb"].sum(), g["a_gb"].sum()
        total.append(
            {"fuente": "TOTAL", "d_gb": d, "p": rotulo, "f_bytes": 1 - a / d, "a_gb": a}
        )
    ahorro_df = pd.concat([ahorro_df, pd.DataFrame(total)], ignore_index=True)
    return {
        "t1_6_calibracion": (
            calib,
            "Umbrales calibrados con la escena estática",
            {"t_pix": 0, "t_area": 5, "estaticos_tx_pct_ciclos": 2},
        ),
        "t1_6_f": (
            pd.DataFrame(f_filas),
            "Fracción transmitida f por tipo de segmento",
            {"f_frames": 4, "f_bytes": 4},
        ),
        "t1_6_ahorro": (
            ahorro_df,
            "Datos a 30 días D y ahorro A = (1-f)D (GB decimales)",
            {
                "s_medio_bytes": 0,
                "fps": 2,
                "d_gb": 2,
                "f_bytes": 4,
                "f_frames": 4,
                "a_gb": 2,
                "p_valor": 4,
            },
        ),
    }


def analizar_grabacion(
    carpeta: Path | str, salida: Path | str, guarda_s: float = 1.0
) -> dict:
    """Pipeline completo. Devuelve {'resultados', 'excluidas', 'barridos', 'escritas'}."""
    carpeta, salida = Path(carpeta), Path(salida)
    ruta_seg = carpeta / "segmentos.csv"
    if not ruta_seg.exists():
        raise ErrorGrabacion(f"{carpeta} no tiene segmentos.csv")
    segmentos = pd.read_csv(ruta_seg)
    frames = leer_frames(carpeta / "frames.csv")
    meta = json.loads((carpeta / "metadata.json").read_text(encoding="utf-8"))
    if not meta.get("valida", False):
        raise ErrorGrabacion(
            "grabación inválida: " + "; ".join(meta.get("motivos_invalida", []))
        )
    resultados, excluidas, barridos = [], {}, []
    for f in ORDEN_FUENTES:
        if f not in meta.get("fuentes_usadas", []):
            continue
        if not meta.get("validez_por_fuente", {}).get(f, {}).get("valida", False):
            excluidas[f] = "fuente inválida: " + "; ".join(
                meta["validez_por_fuente"][f]["motivos"]
            )
            continue
        try:
            seq = cargar_secuencia(carpeta, f, frames, segmentos, guarda_s)
            res = analizar_fuente(seq, segmentos, guarda_s)
        except (ErrorGrabacion, ValueError) as e:
            excluidas[f] = str(e)
            continue
        barridos.append(barrido(seq, res["t_pix"], filtro.candidatos_t_area(40)))
        resultados.append(res)
    escritas = {}
    if resultados:
        for nombre, (df, caption, dec) in tablas(resultados).items():
            base = salida / nombre
            escribir_tabla(
                df, base, caption=caption, label=f"tab:{nombre}", decimales=dec
            )
            escritas[nombre] = base
        bar = pd.concat(barridos, ignore_index=True)
        bar.to_csv(salida / "t1_6_barrido_t_area.csv", index=False)
    return {"resultados": resultados, "excluidas": excluidas,
            "barridos": pd.concat(barridos) if barridos else None, "escritas": escritas}  # fmt: skip
