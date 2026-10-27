"""Metadatos de cada corrida (metadata.json)."""

import json
import platform
import subprocess
import sys
from datetime import datetime
from http.client import HTTPConnection
from importlib import metadata as importlib_metadata
from pathlib import Path

import psutil

from edge_parcial.config import RAIZ, Config

PAQUETES = [
    "edge-parcial",
    "opencv-python",
    "numpy",
    "pandas",
    "psutil",
    "pillow",
    "matplotlib",
    "httpx",
    "pytest",
    "ruff",
]

# Claves que puede usar /status para el RSSI (el firmware no fija el nombre aquí).
_CLAVES_RSSI = ("rssi_dbm", "rssi", "x-rssi-dbm")


def crear_run_id(fuente: str, ahora: datetime | None = None) -> str:
    """run_id con formato AAAAMMDD-HHMMSS-<fuente|todas>."""
    ahora = ahora or datetime.now()
    return f"{ahora:%Y%m%d-%H%M%S}-{fuente}"


def versiones_paquetes() -> dict:
    versiones = {}
    for nombre in PAQUETES:
        try:
            versiones[nombre] = importlib_metadata.version(nombre)
        except importlib_metadata.PackageNotFoundError:
            versiones[nombre] = None
    return versiones


def commit_actual(raiz: Path = RAIZ) -> dict:
    """Hash de HEAD e indicador de cambios sin confirmar (archivos versionados)."""

    def git(*args: str) -> str | None:
        try:
            r = subprocess.run(
                ["git", *args],
                check=False,
                cwd=raiz,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except OSError, subprocess.TimeoutExpired:
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    hash_ = git("rev-parse", "HEAD")
    estado = git("status", "--porcelain", "--untracked-files=no")
    return {"hash": hash_, "sucio": None if estado is None else bool(estado)}


def consultar_status_esp32(ip: str, puerto: int = 80, timeout: float = 3.0) -> dict:
    """Consulta /status de la ESP32-CAM.

    Debe llamarse con el stream cerrado: el servidor admite un solo cliente.
    Devuelve {"fw", "rssi_dbm", "ok", "error"}; nunca lanza por fallos de red.
    """
    resultado = {"fw": None, "rssi_dbm": None, "ok": False, "error": None}
    conn = HTTPConnection(ip, puerto, timeout=timeout)
    try:
        conn.request("GET", "/status", headers={"Connection": "close"})
        resp = conn.getresponse()
        cuerpo = resp.read()
        if resp.status != 200:
            resultado["error"] = f"/status devolvió HTTP {resp.status}"
            return resultado
        datos = json.loads(cuerpo)
    except (OSError, ValueError) as e:
        resultado["error"] = f"/status no disponible: {e}"
        return resultado
    finally:
        conn.close()

    if not isinstance(datos, dict):
        resultado["error"] = "/status no devolvió un objeto JSON"
        return resultado
    resultado["fw"] = datos.get("fw")
    minusculas = {str(k).lower(): v for k, v in datos.items()}
    for clave in _CLAVES_RSSI:
        if clave in minusculas:
            resultado["rssi_dbm"] = minusculas[clave]
            break
    if resultado["fw"] is None:
        resultado["error"] = "/status no trae 'fw'"
        return resultado
    resultado["ok"] = True
    return resultado


def parsear_wifi(texto: str) -> dict:
    """Extrae del texto de `system_profiler SPAirPortDataType` la red actual."""
    campos = {
        "PHY Mode": "modo_phy",
        "Channel": "canal",
        "Transmit Rate": "tasa_transmision_mbps",
        "MCS Index": "mcs",
        "Signal / Noise": "senal_ruido_dbm",
    }
    resultado = dict.fromkeys(campos.values())
    en_bloque = False
    for linea in texto.splitlines():
        s = linea.strip()
        if s.startswith("Current Network Information:"):
            en_bloque = True
            continue
        if not en_bloque:
            continue
        if s.startswith("Other Local Wi-Fi Networks:"):
            break
        clave, sep, valor = s.partition(":")
        if sep and clave in campos and resultado[campos[clave]] is None:
            resultado[campos[clave]] = valor.strip()
    for clave in ("tasa_transmision_mbps", "mcs"):
        try:
            resultado[clave] = float(resultado[clave])
        except TypeError, ValueError:
            resultado[clave] = None
    return resultado


def leer_wifi_mac() -> dict:
    """Tasa de transmisión y datos del enlace Wi-Fi del Mac (None si no hay dato)."""
    try:
        r = subprocess.run(
            ["system_profiler", "SPAirPortDataType"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        texto = r.stdout
    except OSError, subprocess.TimeoutExpired:
        texto = ""
    return parsear_wifi(texto)


def muestrear_cpu(duracion_s: float = 2.0, intervalo_s: float = 0.5) -> dict:
    """Carga de CPU del sistema (%) muestreada con psutil."""
    n = max(1, round(duracion_s / intervalo_s))
    muestras = [psutil.cpu_percent(interval=intervalo_s) for _ in range(n)]
    return {
        "intervalo_s": intervalo_s,
        "muestras_pct": muestras,
        "media_pct": sum(muestras) / len(muestras),
        "max_pct": max(muestras),
    }


def recolectar_metadata(
    cfg: Config,
    run_id: str,
    resoluciones: dict | None = None,
    cpu_duracion_s: float = 2.0,
) -> dict:
    """Metadatos al inicio de la corrida. Consulta /status: stream cerrado."""
    status = consultar_status_esp32(cfg.esp32.ip, cfg.esp32.puerto)
    motivos = []
    if not status["ok"]:
        motivos.append(status["error"])
    return {
        "run_id": run_id,
        "fecha": datetime.now().astimezone().isoformat(),
        "ips": {
            "esp32": cfg.esp32.ip,
            "droidcam": cfg.droidcam.ip,
            "gateway": cfg.gateway_ip,
        },
        "versiones": {
            "python": platform.python_version(),
            "ejecutable": sys.executable,
            "paquetes": versiones_paquetes(),
        },
        "commit": commit_actual(),
        "esp32_status_inicio": {"fw": status["fw"], "rssi_dbm": status["rssi_dbm"]},
        "wifi_mac": leer_wifi_mac(),
        "resoluciones": resoluciones or {},
        "cpu": muestrear_cpu(cpu_duracion_s),
        "valida": not motivos,
        "motivos_invalida": motivos,
    }


def cerrar_metadata(meta: dict, cfg: Config) -> dict:
    """Consulta /status al final (stream cerrado) y valida que `fw` no cambió."""
    status = consultar_status_esp32(cfg.esp32.ip, cfg.esp32.puerto)
    meta["esp32_status_fin"] = {"fw": status["fw"], "rssi_dbm": status["rssi_dbm"]}
    if not status["ok"]:
        meta["motivos_invalida"].append(status["error"])
    elif meta["esp32_status_inicio"]["fw"] != status["fw"]:
        meta["motivos_invalida"].append(
            f"fw cambió durante la serie: {meta['esp32_status_inicio']['fw']!r} "
            f"-> {status['fw']!r}"
        )
    meta["valida"] = not meta["motivos_invalida"]
    return meta


def escribir_metadata(meta: dict, dir_raw: Path | str) -> Path:
    """Escribe <dir_raw>/<run_id>/metadata.json y devuelve su ruta."""
    destino = Path(dir_raw) / meta["run_id"]
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / "metadata.json"
    ruta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return ruta
