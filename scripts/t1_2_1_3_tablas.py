"""Tablas de las Tareas 1.2/1.3 (CSV sin redondear + LaTeX) desde data/raw.

    uv run python scripts/t1_2_1_3_tablas.py [--raw data/raw] [--salida data/processed/tablas]

Tablas oficiales: corrida 1 de cada modo. Corridas inválidas o con reconexiones entre
fotogramas medidos se listan como EXCLUIDAS (nunca se promedian en silencio).
"""

import argparse
import sys
from pathlib import Path

from edge_parcial.analysis.carga import cargar_corridas
from edge_parcial.analysis.tarea_1_2_1_3 import TAREA, generar_tablas
from edge_parcial.config import RAIZ


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw")
    ap.add_argument(
        "--salida", type=Path, default=RAIZ / "data" / "processed" / "tablas"
    )
    args = ap.parse_args(argv)
    corridas = cargar_corridas(args.raw, TAREA)
    if not corridas:
        print(f"No hay corridas de la tarea {TAREA} en {args.raw}", file=sys.stderr)
        return 1
    escritas = generar_tablas(corridas, args.salida)
    for nombre, base in sorted(escritas.items()):
        print(f"{nombre}: {base}.csv / .tex")
    return 0


if __name__ == "__main__":
    sys.exit(main())
