"""Tarea 1.6: análisis de una grabación (f, D, A, f(p)), tablas CSV/LaTeX y figura.

    uv run python scripts/t1_6_analisis.py [--grabacion data/recordings/<run_id>]

Sin --grabacion se usa la más reciente de data/recordings.
"""

import argparse
import sys
from pathlib import Path

from edge_parcial.analysis.figuras_1_6 import figura_f_vs_umbral
from edge_parcial.analysis.tarea_1_6 import ErrorGrabacion, analizar_grabacion
from edge_parcial.config import RAIZ


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--grabacion", type=Path)
    ap.add_argument("--recordings", type=Path, default=RAIZ / "data" / "recordings")
    ap.add_argument("--salida", type=Path, default=RAIZ / "data" / "processed")
    ap.add_argument("--guarda-s", type=float, default=1.0)
    args = ap.parse_args(argv)
    carpeta = args.grabacion
    if carpeta is None:
        todas = sorted(
            p for p in args.recordings.glob("*") if (p / "segmentos.csv").exists()
        )
        if not todas:
            print(f"No hay grabaciones en {args.recordings}", file=sys.stderr)
            return 1
        carpeta = todas[-1]
    try:
        r = analizar_grabacion(carpeta, args.salida, args.guarda_s)
    except ErrorGrabacion as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    for f, motivo in r["excluidas"].items():
        print(f"EXCLUIDA {f}: {motivo}", file=sys.stderr)
    if not r["resultados"]:
        return 1
    elegidos = {x["fuente"]: x["t_area"] for x in r["resultados"]}
    fig = figura_f_vs_umbral(
        r["barridos"], elegidos, args.salida / "t1_6_f_vs_umbral.png"
    )
    for nombre, base in r["escritas"].items():
        print(f"{nombre}: {base}.csv / .tex")
    print(f"figura: {fig}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
