"""Análisis y tablas (Tareas 1.2/1.3, 1.4 y 1.5) desde data/raw hacia data/processed/tablas.

    uv run python scripts/t1_5_analisis.py [--raw data/raw] [--salida data/processed/tablas]

CSV con valores sin redondear y LaTeX con el redondeo solo de presentación. Corridas
inválidas o con reconexiones se listan como EXCLUIDAS (no se promedian).
"""

import argparse
import sys
from pathlib import Path

from edge_parcial.analysis.tarea_1_5 import generar_todo
from edge_parcial.config import RAIZ, RUTA_CONFIG, ErrorConfig, cargar_config


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw")
    ap.add_argument(
        "--salida", type=Path, default=RAIZ / "data" / "processed" / "tablas"
    )
    ap.add_argument("--config", type=Path, default=RUTA_CONFIG)
    args = ap.parse_args(argv)
    try:
        cfg = cargar_config(args.config)
    except ErrorConfig as e:
        print(f"Error de configuración: {e}", file=sys.stderr)
        return 2
    escritas = generar_todo(args.raw, args.salida, cfg)
    if not escritas:
        print(f"No hay corridas analizables en {args.raw}", file=sys.stderr)
        return 1
    for nombre, base in sorted(escritas.items()):
        print(f"{nombre}: {base}.csv / .tex")
    return 0


if __name__ == "__main__":
    sys.exit(main())
