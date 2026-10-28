"""Simulador de datos a 1 Hz para desarrollar y probar el panel (sin hardware).

Uso: uv run python scripts/simular_datos.py [--data-dir data] [--hz 1] [--pasos N]
"""

import argparse
from pathlib import Path

from edge_parcial.panel.datos import rutas_por_defecto
from edge_parcial.panel.simulador import correr


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--hz", type=float, default=1.0)
    ap.add_argument("--pasos", type=int, default=None, help="sin valor = hasta Ctrl+C")
    ap.add_argument("--semilla", type=int, default=None)
    args = ap.parse_args()
    correr(rutas_por_defecto(args.data_dir), args.hz, args.pasos, args.semilla)


if __name__ == "__main__":
    main()
