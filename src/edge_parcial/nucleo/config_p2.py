"""Parámetros de la Parte 2 en config/config.toml (sin tocar `edge_parcial.config`).

Secciones: `[quorum]` (n, ventana_s, gracia_s, timeout_fog_s), `[detector]` (valores
comunes) y `[detector.<fuente>]` (t_pix, t_area, umbral_voto, ... por fuente), y las
rutas opcionales `eventos_csv` y `estado_json` de `[rutas]` (docs/CONTRATO_DATOS.md).
"""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from edge_parcial.config import RAIZ, RUTA_CONFIG, Config, ErrorConfig, cargar_config
from edge_parcial.edge.detector import ParamsDetector

FUENTES = ("esp32", "droidcam", "local")
EVENTOS_CSV_DEFECTO = "data/eventos.csv"
ESTADO_JSON_DEFECTO = "data/estado.json"
_OPCIONALES = (
    "umbral_global", "salto_luminancia", "umbral_oscuro", "tapada_s", "edad_ref_ms",
)  # fmt: skip


@dataclass(frozen=True)
class ConfigP2:
    base: Config
    n_quorum: int
    ventana_s: float
    gracia_s: float
    timeout_fog_s: float
    detector: dict[str, ParamsDetector]
    eventos_csv: Path
    estado_json: Path


def params_detector(datos: dict, fuente: str) -> ParamsDetector:
    """`[detector]` común + `[detector.<fuente>]`; t_pix, t_area y umbral_voto son obligatorios."""
    comun = {k: v for k, v in datos.get("detector", {}).items() if not isinstance(v, dict)}  # fmt: skip
    propio = datos.get("detector", {}).get(fuente)
    if not isinstance(propio, dict):
        raise ErrorConfig(
            f"Falta [detector.{fuente}]: calibra con scripts/t2_2_calibrar.py "
            "(--escribir-config)"
        )
    d = {**comun, **propio}
    for clave in ("t_pix", "t_area", "umbral_voto"):
        if clave not in d:
            raise ErrorConfig(f"Falta la clave '{clave}' en [detector.{fuente}]")
    extra = {k: float(d[k]) for k in _OPCIONALES if k in d}
    if "tam_ancho" in d or "tam_alto" in d:
        extra["tam"] = (int(d.get("tam_ancho", 160)), int(d.get("tam_alto", 120)))
    return ParamsDetector(
        t_pix=float(d["t_pix"]), t_area=float(d["t_area"]),
        umbral_voto=float(d["umbral_voto"]), **extra,
    )  # fmt: skip


def cargar_config_p2(
    ruta: Path | str | None = None, fuentes: tuple[str, ...] = FUENTES
) -> ConfigP2:
    ruta = Path(ruta) if ruta is not None else RUTA_CONFIG
    base = cargar_config(ruta)
    with open(ruta, "rb") as f:
        datos = tomllib.load(f)
    q = datos.get("quorum")
    if not isinstance(q, dict) or "n" not in q:
        raise ErrorConfig("Falta la clave 'n' de la sección [quorum] (N = 3)")
    n = int(q["n"])
    if n < 1:
        raise ErrorConfig("[quorum] n debe ser >= 1")
    rutas = datos.get("rutas", {})
    return ConfigP2(
        base=base,
        n_quorum=n,
        ventana_s=float(q.get("ventana_s", 1.0)),
        gracia_s=float(q.get("gracia_s", 0.25)),
        timeout_fog_s=float(q.get("timeout_fog_s", 1.0)),
        detector={f: params_detector(datos, f) for f in fuentes},
        eventos_csv=RAIZ / str(rutas.get("eventos_csv", EVENTOS_CSV_DEFECTO)),
        estado_json=RAIZ / str(rutas.get("estado_json", ESTADO_JSON_DEFECTO)),
    )


def texto_secciones_detector(params: dict[str, ParamsDetector]) -> str:
    """TOML de `[detector.<fuente>]` con los parámetros calibrados."""
    bloques = []
    for fuente, p in params.items():
        bloques.append(
            f"[detector.{fuente}]\n"
            f"t_pix = {p.t_pix!r}\nt_area = {p.t_area!r}\numbral_voto = {p.umbral_voto!r}\n"
        )
    return "\n".join(bloques)


def escribir_secciones_detector(
    ruta: Path | str, params: dict[str, ParamsDetector]
) -> None:
    """Sustituye (o añade) las secciones `[detector.<fuente>]` de la config, sin tocar el resto."""
    ruta = Path(ruta)
    texto = ruta.read_text(encoding="utf-8")
    for fuente in params:
        texto = re.sub(
            rf"^\[detector\.{fuente}\]\n(?:(?!\[).*\n?)*", "", texto, flags=re.MULTILINE
        )
    texto = texto.rstrip("\n") + "\n\n" + texto_secciones_detector(params)
    ruta.write_text(texto, encoding="utf-8")
