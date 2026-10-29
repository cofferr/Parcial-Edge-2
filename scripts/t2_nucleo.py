"""Núcleo en marcha: tres fuentes -> edge -> quórum, escribiendo eventos.csv y estado.json.

    uv run python scripts/t2_nucleo.py --ventanas

Las rutas salen de config.toml ([rutas] eventos_csv y estado_json; por defecto data/eventos.csv y
data/estado.json). Una línea de log por ventana. Con --ventanas se abren las tres cámaras con la
superposición (q para salir); sin ella, Ctrl+C. La ESP32-CAM admite un solo cliente.
"""

import argparse
import signal
import sys
import threading
from datetime import datetime
from pathlib import Path

from edge_parcial.acquisition.pantalla import PantallaCV2
from edge_parcial.capas.registro import RegistroCapas
from edge_parcial.config import RUTA_CONFIG, ErrorConfig
from edge_parcial.nucleo.config_p2 import cargar_config_p2
from edge_parcial.nucleo.fuentes import construir_entradas
from edge_parcial.nucleo.nucleo import Nucleo
from edge_parcial.nucleo.ventanas import ejecutar_ventanas
from edge_parcial.panel.datos import SUBCARPETA_VIVO


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--ventanas", action="store_true")
    ap.add_argument("--config", type=Path, default=RUTA_CONFIG)
    ap.add_argument(
        "--duracion-s", type=float, default=None, help="termina tras este tiempo"
    )
    ap.add_argument(
        "--capas",
        type=Path,
        default=None,
        help="carpeta para el registro de latencia por capas",
    )
    args = ap.parse_args(argv)
    try:
        cfg = cargar_config_p2(args.config)
    except ErrorConfig as e:
        print(f"Error de configuración: {e}", file=sys.stderr)
        return 2
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-nucleo"
    capas = RegistroCapas(args.capas) if args.capas else None
    nucleo = Nucleo(
        cfg,
        construir_entradas(cfg.base),
        run_id,
        cfg.eventos_csv,
        cfg.estado_json,
        capas=capas,
        carpeta_visor=cfg.base.snapshots_dir / SUBCARPETA_VIVO,
    )
    parar = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: parar.set())
    if args.duracion_s:
        threading.Timer(args.duracion_s, parar.set).start()
    nucleo.iniciar()
    try:
        if args.ventanas:
            pantalla = PantallaCV2()
            try:
                ejecutar_ventanas(nucleo, pantalla, parar=parar.is_set)
            finally:
                pantalla.cerrar()
        else:
            parar.wait()
    finally:
        nucleo.detener()
    return 0


if __name__ == "__main__":
    sys.exit(main())
