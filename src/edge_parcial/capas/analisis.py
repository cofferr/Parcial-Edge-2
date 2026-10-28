"""Análisis de la latencia por capas (Tarea 2.4, docs/DISENO.md §25).

Entrada: `capas_fotogramas.csv` y `capas_ventanas.csv` de una corrida del núcleo.
Por fotograma (en ms; las marcas son `perf_counter_ns` sin redondear):
- Ldevice  = t_ready − t_first (en la local, t_request: inicio del `read()`).
- Ledge    = t_edge_fin − t_ready (cola + cómputo; el cómputo = t_edge_fin − t_edge_ini).
- Lfog     = t_decision − t_voto de su fuente en su ventana.
- L_ventana = t_voto − t_edge_fin: espera de diseño hasta el cierre de la ventana; NO entra
  en Lfog ni en Ltotal.
- Ltotal   = Ldevice + Ledge + Lfog (sin Cloud).
- Extremo a extremo evento→alerta = t_decision − t_inicio = Ltotal + L_ventana.
Los fotogramas tardíos (llegaron al edge con su ventana ya votada) y los de las primeras
ventanas (arranque) se excluyen de las métricas que dependen de la ventana.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from edge_parcial.analysis.estadisticas import estadisticos
from edge_parcial.analysis.tablas import escribir_tabla
from edge_parcial.capas.registro import FUENTES

NS_A_MS = 1e-6
CAPAS = ("device", "edge", "fog")
VENTANAS_ARRANQUE = 2
METRICAS = (
    "device_ms", "edge_ms", "edge_computo_ms", "edge_cola_ms", "fog_ms",
    "ltotal_ms", "l_ventana_ms", "e2e_ms", "tproc_dispositivo_ms",
)  # fmt: skip


def cargar(carpeta: Path | str) -> tuple[pd.DataFrame, pd.DataFrame]:
    carpeta = Path(carpeta)
    enteras = {
        c: "Int64"
        for c in (
            "seq",
            "ventana",
            "t_request_ns",
            "t_first_ns",
            "t_ready_ns",
            "t_edge_ini_ns",
            "t_edge_fin_ns",
            "capture_us",
            "flush_us",
            "jpeg_us",
        )
    }
    fotos = pd.read_csv(carpeta / "capas_fotogramas.csv", dtype=enteras)
    vent_dtypes = {"t_ini_ns": "Int64", "t_decision_ns": "Int64"}
    vent_dtypes |= {f"t_voto_ns_{f}": "Int64" for f in FUENTES}
    ventanas = pd.read_csv(carpeta / "capas_ventanas.csv", dtype=vent_dtypes)
    return fotos, ventanas


def calcular_capas(
    fotos: pd.DataFrame,
    ventanas: pd.DataFrame,
    ventanas_arranque: int = VENTANAS_ARRANQUE,
) -> pd.DataFrame:
    """Una fila por fotograma con cada término de latencia en ms (sin redondear)."""
    v = ventanas.set_index("ventana")
    df = fotos.copy()
    inicio = df["t_first_ns"].fillna(df["t_request_ns"]).astype("Int64")
    df["device_ms"] = (df["t_ready_ns"] - inicio).astype("Float64") * NS_A_MS
    df["edge_ms"] = (df["t_edge_fin_ns"] - df["t_ready_ns"]).astype("Float64") * NS_A_MS
    df["edge_computo_ms"] = (df["t_edge_fin_ns"] - df["t_edge_ini_ns"]).astype("Float64") * NS_A_MS  # fmt: skip
    df["edge_cola_ms"] = (df["t_edge_ini_ns"] - df["t_ready_ns"]).astype("Float64") * NS_A_MS  # fmt: skip
    df["tproc_dispositivo_ms"] = (
        df["capture_us"].astype("Float64") + df["jpeg_us"].astype("Float64")
    ) * 1e-3  # stream: capture + jpeg ("sin espera de sensor"); local: sin dato
    t_dec = df["ventana"].map(v["t_decision_ns"]).astype("Float64")
    t_voto = pd.Series(np.nan, index=df.index, dtype="Float64")
    for f in FUENTES:
        m = df["source"] == f
        t_voto[m] = df.loc[m, "ventana"].map(v[f"t_voto_ns_{f}"]).astype("Float64")
    valido = (df["tardio"] == 0) & (df["ventana"] >= ventanas_arranque) & t_voto.notna() & t_dec.notna()  # fmt: skip
    df["fog_ms"] = (t_dec - t_voto) * NS_A_MS
    df["l_ventana_ms"] = (t_voto - df["t_edge_fin_ns"].astype("Float64")) * NS_A_MS
    df["ltotal_ms"] = df["device_ms"] + df["edge_ms"] + df["fog_ms"]
    df["e2e_ms"] = (t_dec - inicio.astype("Float64")) * NS_A_MS
    df["alerta"] = df["ventana"].map(v["alerta"]).astype("Int64")
    df["valido"] = valido
    # Las métricas que dependen de la ventana solo valen en los fotogramas válidos.
    for c in ("fog_ms", "l_ventana_ms", "ltotal_ms", "e2e_ms"):
        df.loc[~valido, c] = pd.NA
    return df


def identidad_e2e(df: pd.DataFrame) -> float:
    """Máxima desviación (ms) de e2e − (Ltotal + L_ventana); debe ser ~0 (error de coma flotante)."""
    d = df[df["valido"]]
    if d.empty:
        return float("nan")
    return float((d["e2e_ms"] - d["ltotal_ms"] - d["l_ventana_ms"]).abs().max())


def tabla_estadisticos(df: pd.DataFrame, metricas=METRICAS) -> pd.DataFrame:
    """Estadísticos (n, media, mínimo, máximo, desviación, p50, p95) por fuente y métrica."""
    filas = []
    for f in FUENTES:
        d = df[(df["source"] == f) & (df["tardio"] == 0) & (df["ventana"] >= VENTANAS_ARRANQUE)]  # fmt: skip
        for m in metricas:
            # Lfog es una magnitud por (ventana, fuente): no se repite por cada fotograma.
            base = d.drop_duplicates("ventana") if m == "fog_ms" else d
            filas.append({"fuente": f, "metrica": m, **estadisticos(base[m].dropna().astype(float))})  # fmt: skip
    return pd.DataFrame(filas)


def evento_alerta(df: pd.DataFrame) -> pd.DataFrame:
    """e2e evento→alerta: fotogramas con movimiento en ventanas con alerta, con L_ventana incluido.

    Por fuente, y 'ventana' = por ventana, desde el primer fotograma con movimiento de
    cualquier fuente hasta la decisión (peor caso de la ventana).
    """
    d = df[df["valido"] & (df["movimiento"] == 1) & (df["alerta"] == 1)]
    filas = []
    for f in FUENTES:
        filas.append({"grupo": f, **estadisticos(d.loc[d["source"] == f, "e2e_ms"].astype(float))})  # fmt: skip
    peor = d.groupby("ventana")["e2e_ms"].max().astype(float)
    filas.append({"grupo": "ventana (peor caso)", **estadisticos(peor)})
    return pd.DataFrame(filas)


def diferencia_entre_fuentes(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Capa que más contribuye a la diferencia de Ltotal entre fuentes.

    Se toma la fuente con mayor Ltotal medio y la de menor; la diferencia se descompone
    exactamente por capa (las medias se calculan sobre los mismos fotogramas válidos, así
    que Δ(Ltotal) = Δ(Ldevice) + Δ(Ledge) + Δ(Lfog)). Gana la capa con mayor |Δ|.
    """
    d = df[df["valido"]]
    medias = d.groupby("source")[["device_ms", "edge_ms", "fog_ms", "ltotal_ms"]].mean().astype(float)  # fmt: skip
    medias = medias.reindex([f for f in FUENTES if f in medias.index])
    if len(medias) < 2:
        return pd.DataFrame(), ""
    alta, baja = medias["ltotal_ms"].idxmax(), medias["ltotal_ms"].idxmin()
    total = float(medias.loc[alta, "ltotal_ms"] - medias.loc[baja, "ltotal_ms"])
    filas = []
    for capa in CAPAS:
        col = f"{capa}_ms"
        delta = float(medias.loc[alta, col] - medias.loc[baja, col])
        filas.append({
            "capa": capa, "fuente_alta": alta, "fuente_baja": baja,
            "media_alta_ms": float(medias.loc[alta, col]),
            "media_baja_ms": float(medias.loc[baja, col]),
            "delta_ms": delta,
            "pct_de_la_diferencia": 100 * delta / total if total else float("nan"),
        })  # fmt: skip
    tabla = pd.DataFrame(filas)
    capa = str(tabla.loc[tabla["delta_ms"].abs().idxmax(), "capa"])
    return tabla, capa


def escribir_tablas(
    carpeta: Path | str, salida: Path | str, prefijo: str = "t2_4"
) -> dict:
    """Calcula todo y escribe CSV (sin redondear) y LaTeX (redondeado) en `salida`."""
    salida = Path(salida)
    fotos, ventanas = cargar(carpeta)
    df = calcular_capas(fotos, ventanas)
    stats = tabla_estadisticos(df)
    eventos = evento_alerta(df)
    dif, capa = diferencia_entre_fuentes(df)
    escribir_tabla(
        stats, salida / f"{prefijo}_capas",
        caption="Latencia por capas y fuente (ms)", label=f"tab:{prefijo}_capas", decimales=3,
    )  # fmt: skip
    escribir_tabla(
        eventos, salida / f"{prefijo}_evento_alerta",
        caption="Extremo a extremo evento a alerta (ms, incluye L_ventana)",
        label=f"tab:{prefijo}_e2e", decimales=3,
    )  # fmt: skip
    if not dif.empty:
        escribir_tabla(
            dif, salida / f"{prefijo}_diferencia",
            caption="Contribución de cada capa a la diferencia de Ltotal entre fuentes",
            label=f"tab:{prefijo}_dif", decimales=3,
        )  # fmt: skip
    df.to_csv(salida / f"{prefijo}_por_fotograma.csv", index=False)
    resumen = {
        "capa_que_mas_contribuye": capa,
        "max_desviacion_identidad_e2e_ms": identidad_e2e(df),
        "fotogramas": len(df),
        "fotogramas_validos": int(df["valido"].sum()),
        "fotogramas_tardios": int(df["tardio"].sum()),
        "ventanas": len(ventanas),
    }
    (salida / f"{prefijo}_resumen.json").write_text(
        json.dumps(resumen, indent=2), encoding="utf-8"
    )
    return resumen
