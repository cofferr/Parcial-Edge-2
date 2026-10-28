"""Calibración y evaluación offline del detector con una grabación guiada (docs/DISENO.md §23).

Procedimiento común a todas las fuentes, solo con el segmento de calibración (estático):
- T_pix = percentil 99,9 del ruido |f - referencia(>=200 ms)| (mínimo 1).
- T_area = el menor de la rejilla log con <= 1 % de fotogramas estáticos con movimiento.
- umbral_voto = el mayor entre el valor por defecto y el menor de la rejilla (0,05..1)
  que deja <= 1 % de las ventanas estáticas con voto True.
Después se evalúa con los ciclos guionizados: matriz de confusión por ventana y fuente.
Las marcas de tiempo de las grabaciones de red son `t_last_ns` (no se decodificó al
grabar); las de la cámara local, `t_ready_ns`.
"""

import math
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from edge_parcial import filtro
from edge_parcial.edge.detector import (
    S_A_NS,
    DetectorMovimiento,
    ParamsDetector,
    ResultadoFotograma,
    votar,
)

MAX_ESTATICOS = 0.01
GUARDA_S_DEFECTO = 1.0
GUARDA_CALIBRACION_S = 5.0
REJILLA_VOTO = [round(x, 2) for x in np.arange(0.05, 1.0001, 0.05)]


class ErrorCalibracion(Exception):
    """No se puede calibrar con los datos (sin fotogramas, ningún umbral cumple...)."""


@dataclass
class SecuenciaFuente:
    fuente: str
    t_ns: np.ndarray  # int64, creciente
    grises: list[np.ndarray]  # ya preparados (gris, reducido, suavizado)


def cargar_fuente(
    carpeta: Path, fuente: str, tam: tuple[int, int] = filtro.TAM_COMUN
) -> SecuenciaFuente:
    """Lee los JPEG de `<carpeta>/<fuente>/` con las filas válidas de frames.csv.

    Se decodifica en color y se prepara igual que en vivo (IMREAD_COLOR, DISENO §19.8).
    """
    df = pd.read_csv(carpeta / "frames.csv", dtype={"seq": int})
    df = df[(df["source"] == fuente) & (df["warmup"] == 0) & (df["descartado"] == 0)]
    df = df[df["error"].isna() & (df["jpeg_valid"] == 1)]
    col = "t_ready_ns" if fuente == "local" else "t_last_ns"
    df = df.dropna(subset=[col]).sort_values(col)
    t, grises = [], []
    for r in df.itertuples():
        img = cv2.imread(
            str(carpeta / fuente / f"{int(r.seq):06d}.jpg"), cv2.IMREAD_COLOR
        )
        if img is None:
            continue  # sin archivo no hay evaluación posible: se omite, no se inventa
        t.append(int(getattr(r, col)))
        grises.append(filtro.preparar(img, tam))
    return SecuenciaFuente(fuente, np.array(t, dtype=np.int64), grises)


def indices_referencia(t_ns: np.ndarray, edad_ns: int) -> np.ndarray:
    """Para cada fotograma, índice del último con edad >= edad_ns (-1 si no hay)."""
    return np.searchsorted(t_ns, t_ns - edad_ns, side="right") - 1


def _en_rango(t_ns: np.ndarray, ini: int, fin: int) -> np.ndarray:
    return np.flatnonzero((t_ns >= ini) & (t_ns < fin))


def calibrar_fuente(
    seq: SecuenciaFuente,
    ini_ns: int,
    fin_ns: int,
    base: ParamsDetector | None = None,
    ventana_s: float = 1.0,
    percentil: float = 99.9,
    guarda_s: float = GUARDA_CALIBRACION_S,
) -> tuple[ParamsDetector, dict]:
    """Calibra T_pix, T_area y umbral_voto con el segmento estático [ini, fin).

    Se descartan los primeros `guarda_s` del segmento: la persona tarda en quedarse
    quieta (en la grabación real hay movimiento durante los primeros ~4 s).
    """
    base = base or ParamsDetector(t_pix=1.0, t_area=0.0)
    ini_ns += int(guarda_s * S_A_NS)
    ref = indices_referencia(seq.t_ns, int(base.edad_ref_ms * 1e6))
    idx = [i for i in _en_rango(seq.t_ns, ini_ns, fin_ns) if ref[i] >= 0]
    if len(idx) < 10:
        raise ErrorCalibracion(
            f"{seq.fuente}: {len(idx)} fotogramas evaluables de calibración (<10)"
        )
    difs = np.concatenate(
        [cv2.absdiff(seq.grises[i], seq.grises[ref[i]]).ravel() for i in idx]
    )
    t_pix = float(max(1, math.ceil(np.percentile(difs, percentil))))
    fracs = np.array(
        [float(np.mean(cv2.absdiff(seq.grises[i], seq.grises[ref[i]]) > t_pix)) for i in idx]
    )  # fmt: skip
    t_area = next(
        (t for t in filtro.candidatos_t_area() if np.mean(fracs > t) <= MAX_ESTATICOS),
        None,
    )
    if t_area is None:
        raise ErrorCalibracion(
            f"{seq.fuente}: ningún T_area deja <= {100 * MAX_ESTATICOS:.0f} % de estáticos con movimiento"
        )
    # Voto: ventanas de la calibración con la rejilla de umbrales de voto.
    ventana_ns = int(ventana_s * S_A_NS)
    ventanas: dict[int, list[bool]] = {}
    for i, f in zip(idx, fracs, strict=True):
        ventanas.setdefault((int(seq.t_ns[i]) - ini_ns) // ventana_ns, []).append(f > t_area)  # fmt: skip
    fraccion_mov = np.array([np.mean(v) for v in ventanas.values()])
    umbral_voto = next(
        (
            u
            for u in REJILLA_VOTO
            if u >= base.umbral_voto and np.mean(fraccion_mov >= u) <= MAX_ESTATICOS
        ),
        None,
    )
    if umbral_voto is None:
        raise ErrorCalibracion(
            f"{seq.fuente}: ningún umbral de voto deja <= {100 * MAX_ESTATICOS:.0f} % de ventanas estáticas con voto True"
        )
    params = replace(base, t_pix=t_pix, t_area=float(t_area), umbral_voto=float(umbral_voto))  # fmt: skip
    diag = {
        "fuente": seq.fuente,
        "fotogramas_calibracion": len(idx),
        "ventanas_calibracion": len(ventanas),
        "t_pix": t_pix,
        "t_area": float(t_area),
        "umbral_voto": float(umbral_voto),
        "estaticos_con_movimiento": float(np.mean(fracs > t_area)),
        "ventanas_estaticas_voto_true": float(np.mean(fraccion_mov >= umbral_voto)),
    }
    return params, diag


def reproducir(
    seq: SecuenciaFuente, params: ParamsDetector
) -> list[ResultadoFotograma]:
    """Pasa toda la secuencia por el detector real (con estado), como en vivo."""
    det = DetectorMovimiento(params)
    return [
        det.procesar_preparado(g, int(t))
        for g, t in zip(seq.grises, seq.t_ns, strict=True)
    ]


def etiqueta_ventana(ini: int, fin: int, segmentos: pd.DataFrame, guarda_s: float):
    """Tipo del segmento que contiene la ventana entera (tras la guarda inicial); si no, None."""
    g = int(guarda_s * S_A_NS)
    for s in segmentos.itertuples():
        if s.t_ini_ns + g <= ini and fin <= s.t_fin_ns:
            return s.tipo
    return None


def evaluar(
    resultados: dict[str, list[ResultadoFotograma]],
    params: dict[str, ParamsDetector],
    segmentos: pd.DataFrame,
    q: int,
    ventana_s: float = 1.0,
    guarda_s: float = GUARDA_S_DEFECTO,
) -> pd.DataFrame:
    """Voto por ventana de cada fuente sobre la rejilla común y su etiqueta real."""
    ventana_ns = int(ventana_s * S_A_NS)
    t0 = int(segmentos["t_ini_ns"].min())
    n_ventanas = (int(segmentos["t_fin_ns"].max()) - t0) // ventana_ns
    filas = []
    por_ventana = {
        f: _agrupar(r, t0, ventana_ns, n_ventanas) for f, r in resultados.items()
    }
    for k in range(n_ventanas):
        ini = t0 + k * ventana_ns
        fila = {"ventana": k, "tipo": etiqueta_ventana(ini, ini + ventana_ns, segmentos, guarda_s)}  # fmt: skip
        n_true = 0
        for f in resultados:
            voto, bandera, _ = votar(por_ventana[f][k], params[f].umbral_voto)
            fila[f"voto_{f}"], fila[f"bandera_{f}"] = voto, bandera
            n_true += voto
        fila["n_true"], fila["alerta"] = n_true, n_true >= q
        filas.append(fila)
    return pd.DataFrame(filas)


def _agrupar(res, t0: int, ventana_ns: int, n: int) -> list[list[ResultadoFotograma]]:
    cubos: list[list[ResultadoFotograma]] = [[] for _ in range(n)]
    for r in res:
        k = (r.t_ns - t0) // ventana_ns
        if 0 <= k < n:
            cubos[k].append(r)
    return cubos


def matriz_confusion(ventanas: pd.DataFrame, columna_voto: str) -> dict:
    """VP/FN/FP/VN con `actividad` como clase positiva (solo ventanas etiquetadas)."""
    est = ventanas[ventanas["tipo"] == "estatico"][columna_voto]
    act = ventanas[ventanas["tipo"] == "actividad"][columna_voto]
    vp, fn = int(act.sum()), int((~act.astype(bool)).sum())
    fp, vn = int(est.sum()), int((~est.astype(bool)).sum())
    n = vp + fn + fp + vn
    return {
        "ventanas_actividad": vp + fn, "ventanas_estaticas": fp + vn,
        "VP": vp, "FN": fn, "FP": fp, "VN": vn,
        "aciertos": (vp + vn) / n if n else math.nan,
        "tasa_VP": vp / (vp + fn) if vp + fn else math.nan,
        "tasa_FP": fp / (fp + vn) if fp + vn else math.nan,
    }  # fmt: skip
