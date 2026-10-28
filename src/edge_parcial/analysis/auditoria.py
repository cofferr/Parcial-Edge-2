"""Tarea 2.1: parser de nmap/lsof, tabla I por dispositivo y AS ≈ N × I (docs/DISENO.md §26).

Funciones puras (sin red ni subprocesos) salvo `sondear_http`, que hace dos GET cortos.
"""

import re
import secrets
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from http.client import HTTPConnection
from pathlib import Path

import pandas as pd

LOOPBACK = ("127.0.0.1", "[::1]", "::1", "localhost")
COLUMNAS_INTERFACES = [
    "dispositivo", "puerto", "protocolo", "servicio", "version", "estado",
    "cuenta_en_I", "propietario", "cuenta_app", "observaciones",
]  # fmt: skip
PROP_APLICACION = "aplicación del dispositivo"
PROP_CELULAR = "AP / sistema del celular"
PROP_HOST = "sistema o usuario del host"
PROP_SIN_IDENTIFICAR = "sin identificar"
# Aplicación propia de cada fuente (lo que el dispositivo hace en el montaje).
PUERTOS_APLICACION = {("esp32", 80, "tcp"), ("droidcam", 4747, "tcp")}
# El celular es a la vez AP y fuente: DNS (dnsmasq del hotspot) y mDNS son del sistema.
PUERTOS_CELULAR = {
    ("droidcam", 53, "tcp"),
    ("droidcam", 53, "udp"),
    ("droidcam", 5353, "udp"),
}
SERVICIOS_HTTP = ("http", "http-alt", "http-proxy", "https")
PUERTOS_HTTP = (80, 81, 8080, 4747)


@dataclass(frozen=True)
class Escucha:
    """Un socket TCP en LISTEN según lsof."""

    comando: str
    pid: int
    direccion: str
    puerto: int

    @property
    def es_loopback(self) -> bool:
        return self.direccion in LOOPBACK


def parsear_nmap_xml(ruta: Path | str, protocolo_defecto: str = "tcp") -> list[dict]:
    """Filas (puerto, protocolo, estado, servicio, version, razon) de un XML de nmap."""
    filas = []
    try:
        raiz = ET.parse(ruta).getroot()
    except ET.ParseError:
        return []  # XML truncado (escaneo abortado): sin puertos que reportar
    for p in raiz.iterfind("./host/ports/port"):
        estado = p.find("state")
        serv = p.find("service")
        version = ""
        servicio = ""
        if serv is not None:
            servicio = serv.get("name", "")
            version = " ".join(
                x for x in (serv.get("product"), serv.get("version"), serv.get("extrainfo")) if x
            )  # fmt: skip
        filas.append(
            {
                "puerto": int(p.get("portid")),
                "protocolo": p.get("protocol", protocolo_defecto),
                "estado": estado.get("state") if estado is not None else "",
                "servicio": servicio,
                "version": version,
                "razon": estado.get("reason", "") if estado is not None else "",
            }
        )
    return filas


_NOMBRE_LSOF = re.compile(r"^(?P<dir>\[[^\]]+\]|[^:\s]+):(?P<puerto>\d+)$")


def parsear_lsof(texto: str) -> list[Escucha]:
    """Escuchas TCP de la salida de `lsof -nP -iTCP -sTCP:LISTEN`."""
    escuchas = []
    for linea in texto.splitlines()[1:]:
        campos = linea.split()
        if len(campos) < 9 or campos[-1] != "(LISTEN)":
            continue
        m = _NOMBRE_LSOF.match(campos[-2])
        if not m or not campos[1].isdigit():
            continue
        direccion = "0.0.0.0" if m["dir"] == "*" else m["dir"]
        escuchas.append(Escucha(campos[0], int(campos[1]), direccion, int(m["puerto"])))
    return escuchas


def interfaces_host(escuchas: list[Escucha], nmap_filas: list[dict]) -> list[dict]:
    """Interfaces del host: unión de escuchas no loopback (lsof) y puertos abiertos (nmap).

    Una interfaz cuenta si escucha en una dirección distinta de 127.0.0.1. Las escuchas
    solo-loopback se listan (estado `listen-loopback`) pero no cuentan.
    """
    por_clave: dict[tuple[str, int], dict] = {}
    for e in escuchas:
        if e.es_loopback:
            continue
        por_clave[("tcp", e.puerto)] = {
            "puerto": e.puerto, "protocolo": "tcp", "estado": "open",
            "servicio": e.comando, "version": "",
            "observaciones": f"lsof: escucha en {e.direccion} (pid {e.pid})",
        }  # fmt: skip
    for f in nmap_filas:
        if f["estado"] != "open":
            continue
        k = (f["protocolo"], f["puerto"])
        if k in por_clave:
            por_clave[k]["observaciones"] += "; confirmado por nmap"
            por_clave[k]["version"] = por_clave[k]["version"] or f["version"]
        else:
            por_clave[k] = {
                **{c: f[c] for c in ("puerto", "protocolo", "estado", "servicio", "version")},
                "observaciones": "nmap: abierto desde la IP del hotspot",
            }  # fmt: skip
    for e in escuchas:
        if e.es_loopback and ("tcp", e.puerto) not in por_clave:
            por_clave[("tcp-lo", e.puerto)] = {
                "puerto": e.puerto, "protocolo": "tcp", "estado": "listen-loopback",
                "servicio": e.comando, "version": "",
                "observaciones": f"lsof: solo {e.direccion}, no cuenta",
            }  # fmt: skip
    return sorted(por_clave.values(), key=lambda r: (r["protocolo"], r["puerto"]))


def sondear_http(ip: str, puerto: int, timeout: float = 3.0) -> list[str]:
    """Observaciones de un GET / y un GET a una ruta inexistente, sin credenciales."""

    def get(ruta: str) -> int | None:
        conn = HTTPConnection(ip, puerto, timeout=timeout)
        try:
            conn.request("GET", ruta, headers={"Connection": "close"})
            r = conn.getresponse()
            r.read(512)  # basta con el código; no se descarga un stream
            return r.status
        except OSError, ValueError:
            return None
        finally:
            conn.close()

    raiz = get("/")
    if raiz is None:
        return ["HTTP: sin respuesta al sondeo"]
    obs = []
    if raiz in (401, 403):
        obs.append(f"requiere autenticación (GET / → {raiz})")
    elif raiz == 200:
        obs.append("sin autenticación (GET / → 200 sin credenciales)")
    else:
        obs.append(f"GET / → {raiz}")
    if get(f"/{secrets.token_hex(6)}") == 200:
        obs.append("rutas desconocidas devuelven 200")
    return obs


def es_candidato_http(fila: dict) -> bool:
    return fila["protocolo"] == "tcp" and (
        fila["servicio"] in SERVICIOS_HTTP or fila["puerto"] in PUERTOS_HTTP
    )


def propietario(dispositivo: str, puerto: int, protocolo: str) -> str:
    """Quién es dueño de la interfaz: aplicación del dispositivo, AP/sistema del celular..."""
    clave = (dispositivo, puerto, protocolo)
    if clave in PUERTOS_APLICACION:
        return PROP_APLICACION
    if clave in PUERTOS_CELULAR:
        return PROP_CELULAR
    return PROP_HOST if dispositivo == "host" else PROP_SIN_IDENTIFICAR


def tabla_interfaces(por_dispositivo: dict[str, list[dict]]) -> pd.DataFrame:
    """Tabla I: una fila por interfaz; `cuenta_en_I` = puerto abierto (no `open|filtered`)."""
    filas = []
    for dispositivo, interfaces in por_dispositivo.items():
        for f in interfaces:
            dueno = propietario(dispositivo, f["puerto"], f["protocolo"])
            filas.append(
                {
                    "dispositivo": dispositivo,
                    "puerto": f["puerto"],
                    "protocolo": f["protocolo"],
                    "servicio": f.get("servicio", ""),
                    "version": f.get("version", ""),
                    "estado": f["estado"],
                    "cuenta_en_I": f["estado"] == "open",
                    "propietario": dueno,
                    "cuenta_app": f["estado"] == "open" and dueno == PROP_APLICACION,
                    "observaciones": f.get("observaciones", ""),
                }
            )
    return pd.DataFrame(filas, columns=COLUMNAS_INTERFACES)


def calcular_as(
    tabla: pd.DataFrame, dispositivos: list[str], etiqueta: str
) -> pd.DataFrame:
    """AS ≈ N × I sin redondear, por dispositivo (N = 1) y total (N = #, I = promedio).

    AS principal: todas las interfaces expuestas. AS_app (secundario): solo las de aplicación
    del dispositivo; no sustituye al principal.
    """
    filas = []
    for d in dispositivos:
        de = tabla["dispositivo"] == d
        i = float((de & tabla["cuenta_en_I"]).sum())
        i_app = float((de & tabla["cuenta_app"]).sum())
        filas.append(
            {"conjunto": etiqueta, "fila": d, "N": 1, "I": i, "AS": i, "I_app": i_app, "AS_app": i_app}
        )  # fmt: skip
    n = len(dispositivos)
    i_medio = sum(f["I"] for f in filas) / n
    i_app_medio = sum(f["I_app"] for f in filas) / n
    filas.append(
        {
            "conjunto": etiqueta, "fila": "total", "N": n, "I": i_medio, "AS": n * i_medio,
            "I_app": i_app_medio, "AS_app": n * i_app_medio,
        }
    )  # fmt: skip
    return pd.DataFrame(filas)
