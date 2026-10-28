"""Análisis de las Tareas 1.2 (tamaño) y 1.3 (tiempo de transmisión).

Reglas (docs/DISENO.md y docs/DECISIONES_AUTONOMAS.md):
- Se excluyen las filas de warmup, con error o con JPEG inválido.
- ttx = t_last - t_first. Las filas con n_recv = 1 (ttx = 0 es solo el límite de
  resolución) se MARCAN, se excluyen del ttx y se declara su porcentaje.
- Una corrida inválida o con reconexiones entre fotogramas medidos NO se promedia: se
  lista como excluida con su motivo.
- Las tablas oficiales usan la corrida 1; las demás quedan en data/raw y en la tabla de
  consistencia entre corridas.
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd

from edge_parcial.analysis.carga import Corrida
from edge_parcial.analysis.estadisticas import con_prefijo, estadisticos
from edge_parcial.analysis.tablas import escribir_tabla

TAREA = "1.2_1.3"
ORDEN_FUENTES = ("local", "esp32", "droidcam")


def estado_fuente(corrida: Corrida, fuente: str) -> tuple[bool, str]:
    """(utilizable, motivo). Excluye corridas inválidas o con reconexiones."""
    validez = corrida.meta.get("validez_por_fuente", {}).get(fuente)
    if validez is None:
        return False, "fuente ausente en la corrida"
    if not validez["valida"]:
        return False, "inválida: " + "; ".join(validez["motivos"])
    if con_reconexiones(corrida, fuente):
        return False, "con reconexiones entre fotogramas medidos (repetir la corrida)"
    return True, ""


def con_reconexiones(corrida: Corrida, fuente: str) -> bool:
    if corrida.tarea == "1.5":  # e2e: cada muestra abre su propia conexión
        return False
    if corrida.meta.get("lectores", {}).get(fuente, {}).get("con_reconexiones"):
        return True
    df = medidas(corrida, fuente, solo_validas=False)
    if df.empty or (df["endpoint"] == "/capture").any():
        return False
    return df["conexion"].nunique() > 1


def medidas(corrida: Corrida, fuente: str, solo_validas: bool = True) -> pd.DataFrame:
    df = corrida.frames
    df = df[(df["source"] == fuente) & (df["warmup"] == 0)]
    if solo_validas:
        df = df[df["error"].isna() & (df["jpeg_valid"] == 1)]
    return df.sort_values("seq")


def interarribos_ms(df: pd.DataFrame, fuente: str) -> list[float]:
    """t_first[i]-t_first[i-1] (red) o t_ready[i]-t_ready[i-1] (local), misma conexión."""
    col = "t_ready_ns" if fuente == "local" else "t_first_ns"
    d = df.dropna(subset=[col])
    t = d[col].astype("int64").to_numpy()
    conex = d["conexion"].astype("int64").to_numpy()
    dif = np.diff(t) / 1e6
    return [
        float(x) for x, mismo in zip(dif, conex[1:] == conex[:-1], strict=True) if mismo
    ]


def ttx_ms(df: pd.DataFrame) -> tuple[list[float], int, int]:
    """(ttx válidos en ms, filas con n_recv=1, filas con tiempos)."""
    d = df.dropna(subset=["t_first_ns", "t_last_ns", "n_recv"])
    uno = d["n_recv"] == 1
    v = (
        d.loc[~uno, "t_last_ns"].astype("int64")
        - d.loc[~uno, "t_first_ns"].astype("int64")
    ) / 1e6
    return [float(x) for x in v], int(uno.sum()), len(d)


def resumen_fuente(corrida: Corrida, fuente: str) -> dict:
    """Todas las métricas 1.2/1.3 de una fuente en una corrida (sin redondear)."""
    ok, motivo = estado_fuente(corrida, fuente)
    r = {
        "run_id": corrida.run_id,
        "modo": corrida.modo,
        "corrida": corrida.numero,
        "fuente": fuente,
        "utilizable": ok,
        "estado": "ok" if ok else f"EXCLUIDA: {motivo}",
    }
    if not ok:
        return r
    df = medidas(corrida, fuente)
    todas = medidas(corrida, fuente, solo_validas=False)
    r["n_medidas"] = len(todas)
    r["n_validas"] = len(df)
    r["n_descartadas_cola"] = int((todas["descartado"] == 1).sum())
    r.update(con_prefijo(estadisticos(df["payload_bytes"].dropna()), "payload"))
    if fuente == "local":
        r.update(con_prefijo(estadisticos(df["raw_bytes"].dropna()), "raw"))
        enc = (df["t_encode_fin_ns"] - df["t_encode_ini_ns"]).dropna() / 1e6
        r.update(con_prefijo(estadisticos(enc), "codificacion_ms"))
        lect = (df["t_ready_ns"] - df["t_request_ns"]).dropna() / 1e6
        r.update(con_prefijo(estadisticos(lect), "lectura_ms"))
    else:
        valores, n_uno, n_tiempos = ttx_ms(df)
        r["n_ttx"] = len(valores)
        r["n_recv_1"] = n_uno
        r["pct_n_recv_1"] = 100 * n_uno / n_tiempos if n_tiempos else math.nan
        r.update(con_prefijo(estadisticos(valores), "ttx_ms"))
        d = df.dropna(subset=["t_first_ns", "t_last_ns", "n_recv"])
        d = d[d["n_recv"] > 1]
        seg = (
            float(
                (d["t_last_ns"].astype("int64") - d["t_first_ns"].astype("int64")).sum()
            )
            / 1e9
        )
        bits = float(d["payload_bytes"].astype("int64").sum()) * 8
        r["velocidad_efectiva_mbps"] = bits / seg / 1e6 if seg > 0 else math.nan
    inter = interarribos_ms(todas, fuente)
    r["fps_medio"] = 1000 / float(np.mean(inter)) if inter else math.nan
    r.update(con_prefijo(estadisticos(inter), "interarribo_ms"))
    r["huecos_mayores_1s"] = sum(1 for x in inter if x > 1000)
    return r


def resumenes(corridas: list[Corrida]) -> pd.DataFrame:
    filas = []
    for c in corridas:
        if c.tarea != TAREA:
            continue
        for f in ORDEN_FUENTES:
            if f in c.fuentes:
                filas.append(resumen_fuente(c, f))
    return _sin_reemplazadas(pd.DataFrame(filas))


def _sin_reemplazadas(res: pd.DataFrame) -> pd.DataFrame:
    """Quita las unidades excluidas que fueron repetidas con éxito.

    Si para (modo, corrida, fuente) existe una unidad utilizable, las excluidas de esa
    misma clave son intentos fallidos reemplazados (los datos siguen en data/raw). Si no
    hay ninguna utilizable, la exclusión se conserva y se muestra.
    """
    if res.empty:
        return res
    ok = res.groupby(["modo", "corrida", "fuente"])["utilizable"].transform("any")
    return res[res["utilizable"] | ~ok].reset_index(drop=True)


def _rotulo(fila) -> str:
    return fila["fuente"]


def tabla_tamano(res: pd.DataFrame) -> pd.DataFrame:
    """Tabla 1.2: tamaño del fotograma por fuente (bytes). Local: bruto y JPEG q50."""
    filas = []
    for _, r in res.iterrows():
        if not r["utilizable"]:
            filas.append({"fuente": r["fuente"], "tipo": "—", "estado": r["estado"]})
            continue
        base = {"n": r["payload_n"], "estado": r["estado"]}
        claves = ("media", "minimo", "maximo", "desviacion", "p50", "p95")
        if r["fuente"] == "local":
            filas.append(
                {"fuente": "local", "tipo": "bruto (nbytes)", **base}
                | {k: r[f"raw_{k}"] for k in claves}
            )
            filas.append(
                {"fuente": "local", "tipo": "JPEG q50", **base}
                | {k: r[f"payload_{k}"] for k in claves}
            )
        else:
            filas.append(
                {"fuente": r["fuente"], "tipo": "carga JPEG", **base}
                | {k: r[f"payload_{k}"] for k in claves}
            )
    cols = [
        "fuente",
        "tipo",
        "n",
        "media",
        "minimo",
        "maximo",
        "desviacion",
        "p50",
        "p95",
        "estado",
    ]
    return pd.DataFrame(filas).reindex(columns=cols)


def tabla_ttx(res: pd.DataFrame) -> pd.DataFrame:
    """Tabla 1.3: ttx real por fuente de red (ms), con % de filas n_recv=1 excluidas."""
    filas = []
    for _, r in res[res["fuente"] != "local"].iterrows():
        if not r["utilizable"]:
            filas.append({"fuente": r["fuente"], "estado": r["estado"]})
            continue
        fila = {"fuente": r["fuente"], "n_medidas": r["n_medidas"], "n_ttx": r["n_ttx"]}
        fila["pct_n_recv_1"] = r["pct_n_recv_1"]
        for k in ("media", "minimo", "maximo", "desviacion", "p50", "p95"):
            fila[k] = r[f"ttx_ms_{k}"]
        fila["velocidad_efectiva_mbps"] = r["velocidad_efectiva_mbps"]
        fila["estado"] = r["estado"]
        filas.append(fila)
    cols = ["fuente", "n_medidas", "n_ttx", "pct_n_recv_1", "media", "minimo", "maximo",
            "desviacion", "p50", "p95", "velocidad_efectiva_mbps", "estado"]  # fmt: skip
    return pd.DataFrame(filas).reindex(columns=cols)


def tabla_fps(res: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for _, r in res.iterrows():
        if not r["utilizable"]:
            filas.append({"fuente": r["fuente"], "estado": r["estado"]})
            continue
        filas.append(
            {
                "fuente": r["fuente"],
                "fps_medio": r["fps_medio"],
                "interarribo_ms_p50": r["interarribo_ms_p50"],
                "interarribo_ms_p95": r["interarribo_ms_p95"],
                "interarribo_ms_maximo": r["interarribo_ms_maximo"],
                "huecos_mayores_1s": r["huecos_mayores_1s"],
                "estado": r["estado"],
            }
        )
    cols = ["fuente", "fps_medio", "interarribo_ms_p50", "interarribo_ms_p95",
            "interarribo_ms_maximo", "huecos_mayores_1s", "estado"]  # fmt: skip
    return pd.DataFrame(filas).reindex(columns=cols)


def tabla_corridas(res: pd.DataFrame) -> pd.DataFrame:
    """Consistencia entre corridas: una fila por (corrida, fuente), con las excluidas marcadas."""
    cols = ["corrida", "fuente", "run_id", "estado", "n_validas", "payload_media",
            "ttx_ms_media", "pct_n_recv_1", "fps_medio"]  # fmt: skip
    return (
        res.reindex(columns=cols)
        .sort_values(["fuente", "corrida"])
        .reset_index(drop=True)
    )


def generar_tablas(corridas: list[Corrida], salida: Path | str) -> dict[str, Path]:
    """Escribe las tablas 1.2/1.3 por modo (oficial = corrida 1) y la de consistencia."""
    salida = Path(salida)
    res = resumenes(corridas)
    escritas: dict[str, Path] = {}
    if res.empty:
        return escritas
    for modo in sorted(res["modo"].dropna().unique()):
        r_modo = res[res["modo"] == modo]
        oficial = r_modo[r_modo["corrida"] == 1]
        sufijo = f"_{modo}"
        especificaciones = [
            ("t1_2_tamano", tabla_tamano(oficial), "Tamaño del fotograma (bytes), corrida 1, modo " + modo,
             {c: 1 for c in ("media", "desviacion", "p50", "p95")}),
            ("t1_3_ttx", tabla_ttx(oficial), "Tiempo de transmisión ttx (ms), corrida 1, modo " + modo
             + "; se excluyen las filas con n\\_recv = 1 (porcentaje declarado)",
             {"pct_n_recv_1": 1, "velocidad_efectiva_mbps": 2, "media": 3, "minimo": 3,
              "maximo": 3, "desviacion": 3, "p50": 3, "p95": 3}),
            ("t1_3_fps", tabla_fps(oficial), "Ritmo de fotogramas, corrida 1, modo " + modo,
             {"fps_medio": 2, "interarribo_ms_p50": 1, "interarribo_ms_p95": 1,
              "interarribo_ms_maximo": 1}),
            ("t1_2_1_3_corridas", tabla_corridas(r_modo), "Consistencia entre corridas, modo " + modo,
             {"payload_media": 1, "ttx_ms_media": 3, "pct_n_recv_1": 1, "fps_medio": 2}),
        ]  # fmt: skip
        for nombre, df, caption, dec in especificaciones:
            base = salida / f"{nombre}{sufijo}"
            escribir_tabla(
                df, base, caption=caption, label=f"tab:{nombre}{sufijo}", decimales=dec
            )
            escritas[f"{nombre}{sufijo}"] = base
    return escritas
