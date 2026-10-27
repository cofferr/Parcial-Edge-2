"""Tarea 1.1: muestra las tres fuentes (local, ESP32-CAM, DroidCam) con cv2.VideoCapture.

    uv run python scripts/t1_1_tres_fuentes.py

Cierra con "q" o cerrando una ventana. La ESP32-CAM admite UN solo cliente: cierra
navegadores y otras corridas antes de ejecutar. Las IP salen de config/config.toml.
"""

import argparse
import sys
from pathlib import Path

from edge_parcial.acquisition.pantalla import PantallaCV2
from edge_parcial.acquisition.tres_fuentes import VisorTresFuentes, fuentes_desde_config
from edge_parcial.config import RUTA_CONFIG, ErrorConfig, cargar_config


def main(argv: list[str] | None = None, *, pantalla=None, fabrica=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--config", type=Path, default=RUTA_CONFIG)
    ap.add_argument(
        "--fuentes",
        default="local,esp32,droidcam",
        help="subconjunto separado por comas (por defecto las tres)",
    )
    args = ap.parse_args(argv)
    try:
        cfg = cargar_config(args.config)
    except ErrorConfig as e:
        print(f"Error de configuración: {e}", file=sys.stderr)
        return 2
    nombres = tuple(n.strip() for n in args.fuentes.split(",") if n.strip())
    desconocidas = set(nombres) - {"local", "esp32", "droidcam"}
    if desconocidas:
        print(f"Fuentes desconocidas: {sorted(desconocidas)}", file=sys.stderr)
        return 2
    fuentes = fuentes_desde_config(cfg, nombres)
    if "esp32" in nombres:
        print("Recuerda: la ESP32-CAM admite UN solo cliente; cierra navegador/curl.")
    print("Cierra con 'q' o cerrando una ventana.")
    kw = {"fabrica": fabrica} if fabrica else {}
    visor = VisorTresFuentes(fuentes, pantalla or PantallaCV2(), **kw)
    resumen = visor.ejecutar()
    print(f"Cierre: {resumen['motivo_cierre']}")
    for nombre, r in resumen["fuentes"].items():
        estado = "ok" if r["abierta"] and not r["error"] else f"PROBLEMA: {r['error']}"
        print(f"  {nombre}: {r['fotogramas']} fotogramas ({estado})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
