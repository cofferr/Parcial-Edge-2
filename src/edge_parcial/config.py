"""Carga y validación de config/config.toml (IPs y parámetros de cada sesión)."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
RUTA_CONFIG = RAIZ / "config" / "config.toml"
RUTA_EJEMPLO = RAIZ / "config" / "config.example.toml"


class ErrorConfig(Exception):
    """Config ausente o inválida."""


@dataclass(frozen=True)
class FuenteRed:
    ip: str
    distancia_m: float
    # None en DroidCam: se toma de tasa_transmision_mbps de la metadata en cada corrida.
    velocidad_nominal_bps: float | None = None
    velocidad_nominal_fuente: str = ""
    puerto: int = 80
    url_imagen_fija: str = ""


@dataclass(frozen=True)
class FuenteLocal:
    indice_camara: int
    distancia_m: float


@dataclass(frozen=True)
class Config:
    gateway_ip: str
    esp32: FuenteRed
    droidcam: FuenteRed
    local: FuenteLocal
    v_propagacion_m_s: float


def _seccion(datos: dict, nombre: str) -> dict:
    if nombre not in datos or not isinstance(datos[nombre], dict):
        raise ErrorConfig(f"Falta la sección [{nombre}] en la configuración")
    return datos[nombre]


def _clave(seccion: dict, nombre: str, clave: str):
    if clave not in seccion:
        raise ErrorConfig(f"Falta la clave '{clave}' en la sección [{nombre}]")
    return seccion[clave]


def _fuente_red(datos: dict, nombre: str, con_velocidad: bool) -> FuenteRed:
    s = _seccion(datos, nombre)
    velocidad = None
    fuente = ""
    if con_velocidad:
        velocidad = float(_clave(s, nombre, "velocidad_nominal_bps"))
        fuente = str(_clave(s, nombre, "velocidad_nominal_fuente"))
    return FuenteRed(
        ip=str(_clave(s, nombre, "ip")),
        distancia_m=float(_clave(s, nombre, "distancia_m")),
        velocidad_nominal_bps=velocidad,
        velocidad_nominal_fuente=fuente,
        puerto=int(s.get("puerto", 80)),
        url_imagen_fija=str(s.get("url_imagen_fija", "")),
    )


def cargar_config(ruta: Path | str | None = None) -> Config:
    """Lee la configuración con tomllib. Si no existe, indica cómo crearla."""
    ruta = Path(ruta) if ruta is not None else RUTA_CONFIG
    if not ruta.is_file():
        raise ErrorConfig(
            f"No existe {ruta}. Copia config/config.example.toml a "
            "config/config.toml y rellena las IP de la sesión."
        )
    try:
        with open(ruta, "rb") as f:
            datos = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ErrorConfig(f"TOML inválido en {ruta}: {e}") from e

    gateway_ip = str(_clave(_seccion(datos, "red"), "red", "gateway_ip"))
    esp32 = _fuente_red(datos, "esp32", con_velocidad=True)
    droidcam = _fuente_red(datos, "droidcam", con_velocidad=False)
    local = _seccion(datos, "local")
    prop = _seccion(datos, "propagacion")
    return Config(
        gateway_ip=gateway_ip,
        esp32=esp32,
        droidcam=droidcam,
        local=FuenteLocal(
            indice_camara=int(_clave(local, "local", "indice_camara")),
            distancia_m=float(_clave(local, "local", "distancia_m")),
        ),
        v_propagacion_m_s=float(_clave(prop, "propagacion", "v_m_s")),
    )
