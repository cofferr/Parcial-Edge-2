"""Consultas de solo lectura que alimentan el panel (sin Streamlit, fáciles de probar)."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from edge_parcial.panel.datos import FUENTES, Rutas, leer_csv
from edge_parcial.panel.estado import COMPONENTES, leer_estado

ESTADO_OBSOLETO_S = 5.0  # sin latido en este tiempo = sin señal


@dataclass(frozen=True)
class ComponenteVista:
    nombre: str
    estado: str  # "vivo", "sin señal" o "sin datos"
    fps: float | None
    ultima_marca: str
    errores: list[str]
    edad_s: float | None = None  # antigüedad del último latido


def _edad_s(marca: str | None, ahora: datetime) -> float | None:
    if not marca:
        return None
    try:
        return (ahora - datetime.fromisoformat(marca)).total_seconds()
    except ValueError:
        return None


def estado_componentes(
    ruta: Path, ahora: datetime | None = None
) -> list[ComponenteVista]:
    ahora = ahora or datetime.now().astimezone()
    datos = leer_estado(ruta)
    vistas = []
    for nombre in COMPONENTES:
        e = datos.get(nombre)
        if not isinstance(e, dict):
            vistas.append(ComponenteVista(nombre, "sin datos", None, "—", []))
            continue
        edad = _edad_s(e.get("ultima_marca"), ahora)
        # El latido por sí solo no basta: una marca vieja con vivo=true es un componente caído.
        vivo = bool(e.get("vivo")) and (edad is None or edad <= ESTADO_OBSOLETO_S)
        vistas.append(
            ComponenteVista(
                nombre,
                "vivo" if vivo else "sin señal",
                e.get("fps"),
                e.get("ultima_marca") or "—",
                list(e.get("errores_recientes") or []),
                edad,
            )
        )
    return vistas


def preparar_telemetria(df: pd.DataFrame) -> pd.DataFrame:
    """Tipos numéricos y `timestamp` como índice (descarta filas sin marca de tiempo válida)."""
    if df.empty:
        return df
    df = df.copy()
    for c in ("temperatura_c", "humedad_pct", "movimiento"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    return df.dropna(subset=["timestamp"]).set_index("timestamp")


def telemetria_reciente(rutas: Rutas, n: int = 120) -> pd.DataFrame:
    """Últimas n lecturas con tipos numéricos y `timestamp` como índice."""
    return preparar_telemetria(leer_csv(rutas.telemetria, ultimas=n))


def ventanas_recientes(rutas: Rutas, n: int = 20) -> pd.DataFrame:
    """Filas = esp32, droidcam, local, alerta; columnas = número de ventana (0/1)."""
    df = leer_csv(rutas.eventos, ultimas=n)
    if df.empty:
        return df
    columnas = {f"voto_{f}": f for f in FUENTES} | {"alerta": "alerta"}
    faltan = [c for c in columnas if c not in df.columns]
    if faltan:
        return pd.DataFrame()
    tabla = (
        df[list(columnas)].apply(pd.to_numeric, errors="coerce").fillna(0).astype(int)
    )
    tabla.index = df["ventana"].values
    return tabla.rename(columns=columnas).T


@dataclass(frozen=True)
class Evidencia:
    ruta: Path
    identidad: str
    fuente: str
    ts_wall: str
    distancia: str


def evidencias(rutas: Rutas, n: int = 12) -> list[Evidencia]:
    """Últimos reconocimientos cuyo JPEG existe en snapshots (más reciente primero)."""
    df = leer_csv(rutas.reconocimientos, ultimas=n * 3)
    if df.empty or "snapshot" not in df.columns:
        return []
    salida = []
    for fila in df.iloc[::-1].itertuples():
        ruta = (
            rutas.snapshots / Path(fila.snapshot).name
        )  # solo el nombre: sin rutas relativas
        if ruta.is_file():
            salida.append(
                Evidencia(
                    ruta, fila.identidad, fila.fuente, fila.ts_wall, fila.distancia
                )
            )
        if len(salida) == n:
            break
    return salida


@dataclass(frozen=True)
class CapturaPir:
    ruta: Path
    fuente: str
    ts: str


def capturas_pir(rutas: Rutas, n: int = 12) -> list[CapturaPir]:
    """Últimas fotos de evidencia del PIR (columna `foto` de telemetria.csv) cuyo JPEG existe."""
    df = leer_csv(rutas.telemetria, ultimas=n * 5)
    if df.empty or not {"foto", "movimiento", "timestamp"} <= set(df.columns):
        return []
    salida = []
    for fila in df.iloc[::-1].itertuples():
        nombre = Path(str(fila.foto)).name  # solo el nombre: sin rutas relativas
        ruta = rutas.snapshots / nombre
        if fila.movimiento == "1" and nombre.startswith("pir_") and ruta.is_file():
            fuente = nombre.split("_")[1] if nombre.count("_") >= 2 else "—"
            reconocida = ruta.with_name(
                f"{ruta.stem}_reconocido.jpg"
            )  # con el nombre dibujado
            salida.append(
                CapturaPir(
                    reconocida if reconocida.is_file() else ruta, fuente, fila.timestamp
                )
            )
        if len(salida) == n:
            break
    return salida


def parte_de(nombre: str) -> str:
    """Parte del parcial según el prefijo del archivo (t1_, reto1_ → 1; t2_ → 2; ...)."""
    n = nombre.lower()
    for numero in ("1", "2", "3"):
        if n.startswith((f"t{numero}_", f"reto{numero}")):
            return f"Parte {numero}"
    return "Otras"


def tablas_disponibles(rutas: Rutas) -> dict[str, list[Path]]:
    """CSV de data/processed/tablas agrupados por parte."""
    grupos: dict[str, list[Path]] = {}
    for p in sorted(rutas.tablas.glob("*.csv")):
        grupos.setdefault(parte_de(p.name), []).append(p)
    return dict(sorted(grupos.items()))


def figuras_disponibles(rutas: Rutas) -> dict[str, list[Path]]:
    """PNG de data/processed (y de tablas/) agrupados por parte."""
    grupos: dict[str, list[Path]] = {}
    pngs = sorted({*rutas.figuras.glob("*.png"), *rutas.tablas.glob("*.png")})
    for p in pngs:
        grupos.setdefault(parte_de(p.name), []).append(p)
    return dict(sorted(grupos.items()))


# Banderas de eventos.csv -> estado mostrado (el simulador escribe 1/0).
_ESTADO_DE_BANDERA = {
    "movimiento": "movimiento",
    "1": "movimiento",
    "quieto": "quieto",
    "0": "quieto",
    "cambio_global": "quieto",
    "tapada": "tapada",
    "sin_datos": "sin_datos",
    "caida": "sin_datos",
}


@dataclass(frozen=True)
class EstadoFuente:
    voto: bool | None
    estado: str  # movimiento, quieto, tapada o sin_datos


def estado_por_fuente(rutas: Rutas) -> tuple[dict[str, EstadoFuente], bool | None]:
    """Voto y estado de cada fuente y bandera de alerta, de la última ventana de eventos.csv."""
    df = leer_csv(rutas.eventos, ultimas=1)
    vacio = {f: EstadoFuente(None, "sin_datos") for f in FUENTES}
    if df.empty or any(f"bandera_{f}" not in df.columns for f in FUENTES):
        return vacio, None
    fila = df.iloc[-1]
    resultado = {}
    for f in FUENTES:
        voto = str(fila.get(f"voto_{f}", "")).strip()
        bandera = str(fila[f"bandera_{f}"]).strip()
        resultado[f] = EstadoFuente(
            None if voto == "" else voto in ("1", "True", "true"),
            _ESTADO_DE_BANDERA.get(bandera, "sin_datos"),
        )
    alerta = str(fila.get("alerta", "")).strip()
    return resultado, None if alerta == "" else alerta in ("1", "True", "true")


# -- página «Datos» (solo lectura; leer_csv ya ignora una última línea a medias) ----------


def filtrar_eventos(
    df: pd.DataFrame,
    fuente: str = "todas",
    solo_alertas: bool = False,
    marca: str = "todas",
) -> pd.DataFrame:
    """`fuente`: solo ventanas donde esa fuente votó 1. `marca`: valor de la columna marca."""
    if df.empty:
        return df
    if solo_alertas and "alerta" in df.columns:
        df = df[df["alerta"].astype(str).isin(["1", "True", "true"])]
    if fuente != "todas" and f"voto_{fuente}" in df.columns:
        df = df[df[f"voto_{fuente}"].astype(str).isin(["1", "True", "true"])]
    if marca != "todas" and "marca" in df.columns:
        df = df[df["marca"].fillna("") == ("" if marca == "(sin marca)" else marca)]
    return df


def filtrar_reconocimientos(
    df: pd.DataFrame, fuente: str = "todas", identidad: str = "todas"
) -> pd.DataFrame:
    if df.empty:
        return df
    if fuente != "todas" and "fuente" in df.columns:
        df = df[df["fuente"] == fuente]
    if identidad != "todas" and "identidad" in df.columns:
        df = df[df["identidad"] == identidad]
    return df


def valores_distintos(df: pd.DataFrame, columna: str) -> list[str]:
    if df.empty or columna not in df.columns:
        return []
    return sorted({str(v) for v in df[columna].fillna("")} - {""})
