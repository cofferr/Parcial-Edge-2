"""Estadísticos descriptivos: media, mínimo, máximo, desviación, p50 y p95."""

import math

import numpy as np

CLAVES = ("n", "media", "minimo", "maximo", "desviacion", "p50", "p95")


def estadisticos(valores) -> dict:
    """n, media, mínimo, máximo, desviación (muestral, ddof=1), p50 y p95.

    Sin valores devuelve n=0 y NaN. Con un solo valor la desviación es NaN.
    """
    x = np.asarray(
        [float(v) for v in valores if v is not None and not _es_nan(v)], dtype=float
    )
    if x.size == 0:
        return {"n": 0, **dict.fromkeys(CLAVES[1:], math.nan)}
    return {
        "n": int(x.size),
        "media": float(x.mean()),
        "minimo": float(x.min()),
        "maximo": float(x.max()),
        "desviacion": float(x.std(ddof=1)) if x.size > 1 else math.nan,
        "p50": float(np.percentile(x, 50)),
        "p95": float(np.percentile(x, 95)),
    }


def _es_nan(v) -> bool:
    try:
        return bool(np.isnan(float(v)))
    except TypeError, ValueError:
        return True


def con_prefijo(est: dict, prefijo: str) -> dict:
    return {f"{prefijo}_{k}": v for k, v in est.items()}
