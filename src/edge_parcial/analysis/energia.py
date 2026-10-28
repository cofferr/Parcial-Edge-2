"""Parte 3, Tareas 3.1 a 3.3: energía de transmisión de la ESP32-CAM y latencia frente a 1 ms.

Modelo de radio de primer orden (docs/DISENO.md §27):
    E_Tx(k, d) = E_elec·k + E_fs·k·d²   si d <  d0
    E_Tx(k, d) = E_elec·k + E_mp·k·d⁴   si d >= d0,     d0 = √(E_fs / E_mp)
    E_Rx(k)    = E_elec·k   (complemento: energía en el receptor; no entra en 3.1 ni en 3.2)
Todo en julios, sin redondear. Los parámetros salen de `[energia]` de la config con su
campo de cita; `distancia_esp32_ap_m` es obligatoria y la da el autor (no hay valor por defecto).
"""

import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

SEGUNDOS_8H = 8 * 3600
LATENCIA_OBJETIVO_MS = 1.0
CLAVES_PARAMS = ("e_elec_j_bit", "e_fs_j_bit_m2", "e_mp_j_bit_m4", "cita")


class ErrorEnergia(Exception):
    """Falta un parámetro obligatorio o un dato de la Parte 1."""


@dataclass(frozen=True)
class ParamsEnergia:
    e_elec: float  # J/bit
    e_fs: float  # J/bit/m²
    e_mp: float  # J/bit/m⁴
    cita: str
    distancia_m: float  # ESP32-CAM -> punto de acceso


def cargar_params(ruta: Path | str) -> ParamsEnergia:
    with open(ruta, "rb") as f:
        sec = tomllib.load(f).get("energia")
    if not isinstance(sec, dict):
        raise ErrorEnergia("Falta la sección [energia] en la configuración")
    faltan = [k for k in CLAVES_PARAMS if k not in sec]
    if faltan:
        raise ErrorEnergia(f"Faltan claves en [energia]: {', '.join(faltan)}")
    if "distancia_esp32_ap_m" not in sec:
        raise ErrorEnergia(
            "Falta 'distancia_esp32_ap_m' en [energia]: es obligatoria y la da el autor "
            "(distancia física ESP32-CAM -> punto de acceso, en metros). El script no corre sin ella."
        )
    d = float(sec["distancia_esp32_ap_m"])
    if not d > 0:
        raise ErrorEnergia("distancia_esp32_ap_m debe ser > 0")
    return ParamsEnergia(
        e_elec=float(sec["e_elec_j_bit"]),
        e_fs=float(sec["e_fs_j_bit_m2"]),
        e_mp=float(sec["e_mp_j_bit_m4"]),
        cita=str(sec["cita"]),
        distancia_m=d,
    )


def d0(p: ParamsEnergia) -> float:
    """Distancia de cruce entre espacio libre y multitrayecto: √(E_fs / E_mp), en metros."""
    return math.sqrt(p.e_fs / p.e_mp)


def regimen(p: ParamsEnergia, d: float) -> tuple[str, str]:
    """('espacio_libre' | 'multitrayecto', razonamiento) comparando d con d0."""
    cruce = d0(p)
    if d < cruce:
        return "espacio_libre", (
            f"d0 = √(E_fs/E_mp) = √({p.e_fs:.6g}/{p.e_mp:.6g}) = {cruce:.6g} m; "
            f"d = {d:.6g} m < d0, así que el amplificador sigue el modelo de espacio libre (E_fs·k·d²)."
        )
    return "multitrayecto", (
        f"d0 = √(E_fs/E_mp) = √({p.e_fs:.6g}/{p.e_mp:.6g}) = {cruce:.6g} m; "
        f"d = {d:.6g} m >= d0, así que el amplificador sigue el modelo de multitrayecto (E_mp·k·d⁴)."
    )


def e_tx(p: ParamsEnergia, k_bits: float, d: float) -> float:
    """Energía (J) de transmitir k bits a distancia d."""
    reg, _ = regimen(p, d)
    amp = p.e_fs * d**2 if reg == "espacio_libre" else p.e_mp * d**4
    return p.e_elec * k_bits + amp * k_bits


def e_rx(p: ParamsEnergia, k_bits: float) -> float:
    """Energía (J) de recibir k bits: E_elec·k. Es del receptor (el punto de acceso)."""
    return p.e_elec * k_bits


def _leer(ruta: Path | str) -> pd.DataFrame:
    ruta = Path(ruta)
    if not ruta.is_file():
        raise ErrorEnergia(
            f"No existe {ruta} (genera las tablas de la Parte 1 primero)"
        )
    return pd.read_csv(ruta)


def tamano_esp32_bits(ruta_tamano: Path | str) -> dict:
    """k de la Tarea 1.2 (carga JPEG de la ESP32-CAM, corridas aisladas) en bits."""
    t = _leer(ruta_tamano)
    fila = t[(t["fuente"] == "esp32") & (t["tipo"] == "carga JPEG")]
    if fila.empty or str(fila.iloc[0]["estado"]) != "ok":
        raise ErrorEnergia("La Tarea 1.2 no tiene un tamaño utilizable de la ESP32-CAM")
    f = fila.iloc[0]
    return {
        "media": 8 * float(f["media"]),
        "minimo": 8 * float(f["minimo"]),
        "maximo": 8 * float(f["maximo"]),
    }


def fps_esp32(ruta_fps: Path | str) -> float:
    t = _leer(ruta_fps)
    fila = t[t["fuente"] == "esp32"]
    if fila.empty or str(fila.iloc[0]["estado"]) != "ok":
        raise ErrorEnergia("La Tarea 1.3 no tiene un FPS utilizable de la ESP32-CAM")
    return float(fila.iloc[0]["fps_medio"])


def fracciones_esp32(ruta_ahorro: Path | str) -> pd.DataFrame:
    """f de la Tarea 1.6 de la ESP32-CAM por proporción de actividad p (y la mezcla real)."""
    t = _leer(ruta_ahorro)
    t = t[t["fuente"] == "esp32"]
    if t.empty:
        raise ErrorEnergia("La Tarea 1.6 no tiene filas de la ESP32-CAM")
    return t[["p", "p_valor", "f_frames", "f_bytes"]].reset_index(drop=True)


def tarea_3_1_rx(p: ParamsEnergia, k: dict) -> pd.DataFrame:
    """Complemento aparte: E_Rx(k) para el mismo k medio, mínimo y máximo (receptor)."""
    nota = "complemento (receptor = punto de acceso); NO entra en E_Tx de 3.1 ni en el ahorro de 3.2"
    return pd.DataFrame([
        {"k_tipo": t, "k_bits": b, "E_Rx_J": e_rx(p, b), "nota": nota} for t, b in k.items()
    ])  # fmt: skip


def tarea_3_1(p: ParamsEnergia, k: dict) -> pd.DataFrame:
    """Energía por fotograma para k medio, mínimo y máximo."""
    reg, razon = regimen(p, p.distancia_m)
    filas = []
    for tipo, bits in k.items():
        total = e_tx(p, bits, p.distancia_m)
        elec = p.e_elec * bits
        filas.append({
            "k_tipo": tipo, "k_bits": bits, "d_m": p.distancia_m, "d0_m": d0(p),
            "regimen": reg, "E_electronica_J": elec, "E_amplificador_J": total - elec,
            "E_Tx_J": total, "razonamiento": razon, "cita": p.cita,
        })  # fmt: skip
    return pd.DataFrame(filas)


def tarea_3_2(p: ParamsEnergia, k_media_bits: float, fps: float, fracciones: pd.DataFrame, segundos: float = SEGUNDOS_8H) -> pd.DataFrame:  # fmt: skip
    """8 h con el FPS medido: transmitir todos frente a solo la fracción f (por frames y por bytes)."""
    n = fps * segundos  # fotogramas en el periodo (sin redondear)
    e_frame = e_tx(p, k_media_bits, p.distancia_m)
    e_todos = n * e_frame
    filas = []
    for r in fracciones.itertuples():
        for criterio, f in (("f_frames", r.f_frames), ("f_bytes", r.f_bytes)):
            e_f = f * e_todos
            filas.append({
                "p": r.p, "criterio_f": criterio, "f": f, "fps": fps, "segundos": segundos,
                "fotogramas_totales": n, "fotogramas_transmitidos": f * n,
                "E_por_fotograma_J": e_frame, "E_todos_J": e_todos, "E_filtrado_J": e_f,
                "ahorro_J": e_todos - e_f, "ahorro_pct": 100 * (e_todos - e_f) / e_todos,
            })  # fmt: skip
    return pd.DataFrame(filas)


def tarea_3_3(ruta_reto1: Path | str) -> pd.DataFrame:
    """L medido de DroidCam (e2e en frío y régimen estable) frente a 1 ms: razón y diferencia."""
    t = _leer(ruta_reto1)
    t = t[t["modo"] == "aislada"]
    casos = (("e2e en frío", "droidcam"), ("régimen estable", "droidcam (régimen)"))
    filas = []
    for etiqueta, fuente in casos:
        fila = t[t["fuente"] == fuente]
        if fila.empty:
            raise ErrorEnergia(f"El Reto 1 no tiene la fila '{fuente}' (aislada)")
        r = fila.iloc[0]
        for est in ("media_ms", "p50_ms", "p95_ms"):
            L = float(r[est])
            filas.append({
                "caso": etiqueta, "definicion_L": r["definicion_L"], "estadistico": est[:-3],
                "L_medido_ms": L, "objetivo_ms": LATENCIA_OBJETIVO_MS,
                "razon": L / LATENCIA_OBJETIVO_MS,
                "diferencia_ms": L - LATENCIA_OBJETIVO_MS,
            })  # fmt: skip
    return pd.DataFrame(filas)
