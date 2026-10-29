"""Lectura del histórico de sesiones (solo lectura, tolerante a filas viejas y a medias).

Cada CSV de datos puede tener: el archivo actual, con filas de varias sesiones (columna
`session_id`; las filas de antes de existir esa columna quedan como «(sin sesión)»), y los
archivos apartados al cambiar la cabecera (`<nombre>.<algo>-AAAAMMDD-HHMMSS.csv`), cuyas filas
se etiquetan como «previa AAAAMMDD-HHMMSS».
"""

import re
from datetime import date
from pathlib import Path

import pandas as pd

from edge_parcial.panel.datos import leer_csv

SIN_SESION = "(sin sesión)"
_FECHA_ARCHIVO = re.compile(r"-(\d{8}-\d{6})$")


def archivos_apartados(ruta: Path) -> list[Path]:
    return sorted(ruta.parent.glob(f"{ruta.stem}.*-*{ruta.suffix}"))


def _etiquetar(df: pd.DataFrame, etiqueta: str, origen: str) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    if "session_id" not in df.columns:
        df["session_id"] = etiqueta
    else:
        df["session_id"] = df["session_id"].fillna("").replace("", etiqueta)
    df["origen"] = origen
    return df


def leer_historico(
    ruta: Path | str, incluir_apartados: bool = False, ultimas: int | None = None
) -> pd.DataFrame:
    """Archivo actual (+ apartados). `ultimas`: se aplica por archivo, para no cargar todo."""
    ruta = Path(ruta)
    partes = [_etiquetar(leer_csv(ruta, ultimas), SIN_SESION, ruta.name)]
    if incluir_apartados:
        for a in archivos_apartados(ruta):
            m = _FECHA_ARCHIVO.search(a.stem)
            etiqueta = f"previa {m.group(1)}" if m else "previa"
            partes.append(_etiquetar(leer_csv(a, ultimas), etiqueta, a.name))
    partes = [p for p in partes if not p.empty]
    return (
        pd.concat(partes, ignore_index=True, sort=False) if partes else pd.DataFrame()
    )


def sesiones(df: pd.DataFrame) -> list[str]:
    """Sesiones presentes, la más reciente primero."""
    if df.empty or "session_id" not in df.columns:
        return []
    return sorted({str(s) for s in df["session_id"]}, reverse=True)


def _dia(df: pd.DataFrame, columna_ts: str) -> pd.Series:
    """Fecha local escrita en el propio CSV (primeros 10 caracteres del ISO 8601)."""
    return pd.to_datetime(
        df[columna_ts].astype(str).str.slice(0, 10), errors="coerce"
    ).dt.date


def filtrar(
    df: pd.DataFrame,
    columna_ts: str,
    sesion: str | None = None,
    desde: date | None = None,
    hasta: date | None = None,
) -> pd.DataFrame:
    """Filtra por sesión y por rango de fechas (inclusive)."""
    if df.empty:
        return df
    if sesion:
        df = df[df["session_id"] == sesion]
    if (desde or hasta) and columna_ts in df.columns and not df.empty:
        dia = _dia(df, columna_ts)
        if desde:
            df = df[dia >= desde]
            dia = _dia(df, columna_ts) if not df.empty else dia
        if hasta and not df.empty:
            df = df[_dia(df, columna_ts) <= hasta]
    return df


def resumen(df: pd.DataFrame, columna_ts: str) -> tuple[int, str]:
    """(número de filas, «desde» legible)."""
    if df.empty or columna_ts not in df.columns:
        return len(df), "—"
    t = pd.to_datetime(
        df[columna_ts].astype(str).str.slice(0, 19), errors="coerce"
    ).dropna()
    return len(df), "—" if t.empty else str(t.min())
