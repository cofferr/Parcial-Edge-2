"""Latido del sistema: estado.json con una entrada por componente.

Varios procesos (BLE, rostros, núcleo) aportan su entrada; cada uno la fusiona con
la existente bajo un candado de archivo y reemplaza el JSON de forma atómica
(archivo temporal + rename), de modo que un lector nunca ve un archivo a medias.
"""

import fcntl
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

COMPONENTES = (
    "camara_esp32",
    "camara_droidcam",
    "camara_local",
    "ble",
    "servicio_rostros",
    "nucleo",
)
MAX_ERRORES = 5


def entrada(
    vivo: bool,
    fps: float | None = None,
    ultima_marca: str | None = None,
    errores: list[str] | None = None,
) -> dict:
    """Entrada de un componente con las claves fijas del contrato."""
    return {
        "vivo": bool(vivo),
        "fps": fps,
        "ultima_marca": ultima_marca,
        "errores_recientes": list(errores or [])[-MAX_ERRORES:],
    }


def ahora_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def leer_estado(ruta: Path | str) -> dict:
    """Devuelve el estado o {} si falta o no es JSON válido."""
    try:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    return datos if isinstance(datos, dict) else {}


def _escribir_atomico(ruta: Path, datos: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=".estado-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ruta)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def escribir_estado(ruta: Path | str, datos: dict) -> None:
    """Reemplaza todo el estado (lo usa el simulador)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    _escribir_atomico(ruta, datos)


def actualizar_componente(ruta: Path | str, nombre: str, datos: dict) -> None:
    """Fusiona la entrada de un componente sin pisar las de los demás."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta.with_name(ruta.name + ".lock"), "w") as candado:
        fcntl.flock(candado, fcntl.LOCK_EX)
        actual = leer_estado(ruta)
        actual[nombre] = datos
        _escribir_atomico(ruta, actual)
