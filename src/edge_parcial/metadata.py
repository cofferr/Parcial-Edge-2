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

# Clave del RSSI en el JSON de /status (X-Rssi-Dbm es solo la cabecera de stream/capture).
CLAVE_RSSI = "rssi"
FUENTES = ("local", "esp32", "droidcam")
MOTIVO_EFECTOS = (
    "no se confirmó que Center Stage y los efectos de video estén desactivados "
    "(--confirmo-efectos-desactivados)"
)
TIMEOUT_STATUS_S = 3.0
REINTENTOS_STATUS = 1


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


def _consultar_status_una_vez(ip: str, puerto: int, timeout: float) -> dict:
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
        resultado["error"] = f"/status no disponible: {type(e).__name__}: {e}"
        return resultado
    finally:
        conn.close()

    if not isinstance(datos, dict):
        resultado["error"] = "/status no devolvió un objeto JSON"
        return resultado
    resultado["fw"] = datos.get("fw")
    resultado["rssi_dbm"] = datos.get(CLAVE_RSSI)
    faltan = [
        n
        for n, v in (("fw", resultado["fw"]), (CLAVE_RSSI, resultado["rssi_dbm"]))
        if v is None
    ]
    if faltan:
        resultado["error"] = f"/status no trae: {', '.join(faltan)}"
        return resultado
    resultado["ok"] = True
    return resultado


def consultar_status_esp32(
    ip: str,
    puerto: int = 80,
    timeout: float = TIMEOUT_STATUS_S,
    reintentos: int = REINTENTOS_STATUS,
) -> dict:
    """Consulta /status de la ESP32-CAM (timeout corto y como máximo un reintento).

    Debe llamarse con el stream cerrado: el servidor admite un solo cliente.
    Devuelve {"fw", "rssi_dbm", "ok", "error", "intentos"}; el error es el literal
    del último intento. Nunca lanza por fallos de red.
    """
    for intento in range(1, reintentos + 2):
        resultado = _consultar_status_una_vez(ip, puerto, timeout)
        resultado["intentos"] = intento
        if resultado["ok"]:
            break
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


def _validar(meta: dict) -> None:
    """valida = todas las fuentes usadas en la corrida son válidas."""
    meta["valida"] = all(v["valida"] for v in meta["validez_por_fuente"].values())
    meta["motivos_invalida"] = [
        f"{fuente}: {m}"
        for fuente, v in meta["validez_por_fuente"].items()
        for m in v["motivos"]
    ]


def recolectar_metadata(
    cfg: Config,
    run_id: str,
    fuentes: tuple[str, ...] = FUENTES,
    resoluciones: dict | None = None,
    cpu_duracion_s: float = 2.0,
    efectos_confirmados: bool = False,
) -> dict:
    """Metadatos al inicio de la corrida.

    Solo las fuentes usadas cuentan para la validez. /status de la ESP32-CAM se
    consulta únicamente si "esp32" está en `fuentes` (stream cerrado).
    Cámara local: sin la confirmación manual de que Center Stage y los efectos de video
    están desactivados (`efectos_confirmados`), la fuente queda inválida.
    """
    desconocidas = set(fuentes) - set(FUENTES)
    if desconocidas:
        raise ValueError(f"Fuentes desconocidas: {sorted(desconocidas)}")
    validez = {f: {"valida": True, "motivos": []} for f in fuentes}
    status_inicio = None
    if "esp32" in fuentes:
        status = consultar_status_esp32(cfg.esp32.ip, cfg.esp32.puerto)
        status_inicio = status
        if not status["ok"]:
            validez["esp32"] = {"valida": False, "motivos": [status["error"]]}
    camara_local = None
    if "local" in fuentes:
        camara_local = {"efectos_desactivados_confirmados": bool(efectos_confirmados)}
        if not efectos_confirmados:
            validez["local"] = {"valida": False, "motivos": [MOTIVO_EFECTOS]}
    meta = {
        "run_id": run_id,
        "fecha": datetime.now().astimezone().isoformat(),
        "fuentes_usadas": list(fuentes),
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
        "esp32_status_inicio": status_inicio,
        "wifi_mac_inicio": leer_wifi_mac(),
        "resoluciones": resoluciones or {},
        "camara_local": camara_local,
        "cpu": muestrear_cpu(cpu_duracion_s),
        "validez_por_fuente": validez,
    }
    _validar(meta)
    return meta


def registrar_camara_local(meta: dict, propiedades: dict, resumen: dict) -> dict:
    """Guarda resolución solicitada y real, FPS reportado y propiedades de la cámara.

    Si la resolución real difiere de la solicitada (o la fuente se abandonó), la fuente
    local queda inválida con el motivo. No se fuerza el FPS: se registra el reportado.
    """
    cam = meta.setdefault("camara_local", {}) or {}
    solicitada = resumen.get("resolucion_solicitada")
    real = resumen.get("resolucion_real")
    cam.update(
        {
            "resolucion_solicitada": list(solicitada) if solicitada else None,
            "resolucion_real": list(real) if real else None,
            "fps_reportado": propiedades.get("fps_reportado"),
            "backend": propiedades.get("backend"),
            "fourcc": propiedades.get("fourcc"),
            "apertura_ns": propiedades.get("apertura_ns"),
            "indice": propiedades.get("indice"),
        }
    )
    meta["camara_local"] = cam
    if real:
        meta.setdefault("resoluciones", {})["local"] = list(real)
    validez = meta["validez_por_fuente"].setdefault(
        "local", {"valida": True, "motivos": []}
    )
    for motivo in resumen.get("motivos_invalida", []):
        if motivo not in validez["motivos"]:
            validez["motivos"].append(motivo)
    validez["valida"] = not validez["motivos"]
    _validar(meta)
    return meta


def cerrar_metadata(meta: dict, cfg: Config) -> dict:
    """Cierre de la corrida: Wi-Fi del Mac y, si se usó la ESP32, /status final.

    La tasa Wi-Fi se guarda al inicio y al cierre (es una instantánea que varía).
    Valida que `fw` no cambió dentro de la serie.
    """
    meta["wifi_mac_fin"] = leer_wifi_mac()
    if "esp32" in meta["fuentes_usadas"]:
        status = consultar_status_esp32(cfg.esp32.ip, cfg.esp32.puerto)
        meta["esp32_status_fin"] = status
        motivos = meta["validez_por_fuente"]["esp32"]["motivos"]
        if not status["ok"]:
            motivos.append(status["error"])
        else:
            inicio = (meta["esp32_status_inicio"] or {}).get("fw")
            if inicio != status["fw"]:
                motivos.append(
                    f"fw cambió durante la serie: {inicio!r} -> {status['fw']!r}"
                )
        meta["validez_por_fuente"]["esp32"]["valida"] = not motivos
    _validar(meta)
    return meta


def escribir_metadata(meta: dict, dir_raw: Path | str) -> Path:
    """Escribe <dir_raw>/<run_id>/metadata.json y devuelve su ruta."""
    destino = Path(dir_raw) / meta["run_id"]
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / "metadata.json"
    ruta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return ruta
