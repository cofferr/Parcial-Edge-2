"""Lectura y escritura de las IP de la ESP32 y de DroidCam en config/config.toml."""

import ipaddress
import re
from pathlib import Path

from edge_parcial.config import RUTA_CONFIG, ErrorConfig, cargar_config
from edge_parcial.csv_anexar import copia_con_fecha

SECCIONES = ("esp32", "droidcam")


def validar_ip(texto: str) -> str:
    """Devuelve la IPv4 normalizada o lanza ErrorConfig con un mensaje en español."""
    try:
        return str(ipaddress.IPv4Address(texto.strip()))
    except ipaddress.AddressValueError as e:
        raise ErrorConfig(
            f"IP inválida: {texto!r} (se espera IPv4, p. ej. 192.168.43.100)"
        ) from e


def leer_ips(ruta: Path | str | None = None) -> dict[str, str]:
    """IP actuales por sección; vacías si la config no existe o no se puede leer."""
    try:
        cfg = cargar_config(ruta)
    except ErrorConfig:
        return {s: "" for s in SECCIONES}
    return {"esp32": cfg.esp32.ip, "droidcam": cfg.droidcam.ip}


def guardar_ips(
    esp32: str, droidcam: str, ruta: Path | str | None = None
) -> dict[str, str]:
    """Sustituye `ip` en [esp32] y [droidcam] conservando el resto del archivo y sus comentarios.

    Los procesos ya en marcha no la releen: hay que reiniciarlos.
    """
    ruta = Path(ruta) if ruta is not None else RUTA_CONFIG
    nuevas = {"esp32": validar_ip(esp32), "droidcam": validar_ip(droidcam)}
    if not ruta.is_file():
        raise ErrorConfig(
            f"No existe {ruta}. Copia config/config.example.toml a config/config.toml."
        )
    texto = ruta.read_text(encoding="utf-8")
    for seccion, ip in nuevas.items():
        patron = re.compile(
            rf'(^\[{seccion}\][^\[]*?^ip\s*=\s*)"[^"\n]*"', re.MULTILINE | re.DOTALL
        )
        texto, n = patron.subn(lambda m, ip=ip: f'{m.group(1)}"{ip}"', texto, count=1)
        if n == 0:
            raise ErrorConfig(
                f"No se encontró la clave 'ip' en la sección [{seccion}] de {ruta}"
            )
    copia_con_fecha(ruta)  # nunca se pierde la configuración anterior
    ruta.write_text(texto, encoding="utf-8")
    return nuevas
