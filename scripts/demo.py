"""Lanza la demo: panel, servicio de rostros y módulo BLE (Ctrl+C cierra todo).

Uso:
  uv run python scripts/demo.py                  # con hardware BLE
  uv run python scripts/demo.py --simular        # datos simulados, sin BLE
  uv run python scripts/demo.py --sin-rostros    # omite el servicio de rostros
  uv run python scripts/demo.py --sin-nucleo     # omite el núcleo (cámaras)

También basta `uv run streamlit run app/main.py`: el panel lanza los componentes él mismo.
"""

import argparse
import logging
import signal
from pathlib import Path

from edge_parcial.panel.orquestador import (
    PUERTO_PANEL,
    Orquestador,
    proceso_nucleo,
    procesos_demo,
)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--puerto-panel", type=int, default=PUERTO_PANEL)
    ap.add_argument(
        "--simular", action="store_true", help="simulador en lugar del módulo BLE"
    )
    ap.add_argument("--sin-ble", action="store_true")
    ap.add_argument("--sin-rostros", action="store_true")
    ap.add_argument("--sin-nucleo", action="store_true", help="no lanza el núcleo")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    # El núcleo abre las tres cámaras; con --simular no hay cámaras que abrir.
    con_nucleo = not (args.sin_nucleo or args.simular)
    procesos = procesos_demo(
        args.data_dir,
        args.puerto_panel,
        ble=not args.sin_ble,
        rostros=not args.sin_rostros,
        simular=args.simular,
        ganchos=[lambda: proceso_nucleo(args.data_dir)] if con_nucleo else [],
    )
    orq = Orquestador(procesos)
    # Las señales se convierten en KeyboardInterrupt para pasar por el mismo cierre.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        orq.lanzar()
        print(f"Panel en http://127.0.0.1:{args.puerto_panel}  (Ctrl+C para cerrar)")
        orq.esperar()
    except KeyboardInterrupt:
        pass
    finally:
        orq.detener()


if __name__ == "__main__":
    main()
