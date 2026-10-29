"""Restaura datos desde data/_respaldo/<fecha>/ SIN sobrescribir nada.

    uv run python scripts/restaurar_respaldo.py --listar
    uv run python scripts/restaurar_respaldo.py 20261028-201500          # esa copia
    uv run python scripts/restaurar_respaldo.py ultimo

Por cada archivo de la copia:
  - si no existe en data/ -> se copia tal cual;
  - si existe y es idéntico -> no se hace nada;
  - si existe y es distinto -> se copia como `<nombre>.restaurado-<fecha>.csv` al lado.
rostros_conocidos/ se restaura igual (solo se añaden las muestras que faltan; las distintas se
guardan con sufijo `.restaurado-<fecha>`). No se borra ni se mueve nada.
"""

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

from edge_parcial.csv_anexar import ruta_libre
from edge_parcial.panel.datos import rutas_por_defecto
from edge_parcial.panel.respaldo import CARPETA, SUBCARPETA_ROSTROS
from edge_parcial.rostros.reconocedor import CARPETA_ROSTROS


def copias(base: Path) -> list[Path]:
    return sorted(p for p in (base / CARPETA).glob("*") if p.is_dir())


def _restaurar_archivo(origen: Path, destino: Path, etiqueta: str) -> str:
    if not destino.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origen, destino)
        return "copiado"
    if filecmp.cmp(origen, destino, shallow=False):
        return "idéntico"
    alterno = ruta_libre(
        destino.with_name(f"{destino.stem}.restaurado-{etiqueta}{destino.suffix}")
    )
    shutil.copy2(origen, alterno)
    return f"distinto -> {alterno.name}"


def restaurar(copia: Path, base: Path, rostros: Path) -> list[tuple[str, str]]:
    etiqueta = copia.name
    informe = []
    for f in sorted(copia.glob("*.csv")):
        informe.append((f.name, _restaurar_archivo(f, base / f.name, etiqueta)))
    origen_rostros = copia / SUBCARPETA_ROSTROS
    if origen_rostros.is_dir():
        for f in sorted(p for p in origen_rostros.rglob("*") if p.is_file()):
            rel = f.relative_to(origen_rostros)
            informe.append(
                (
                    f"rostros_conocidos/{rel}",
                    _restaurar_archivo(f, rostros / rel, etiqueta),
                )
            )
    return informe


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument(
        "copia", nargs="?", help="fecha de la copia (AAAAMMDD-HHMMSS) o «ultimo»"
    )
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--rostros", type=Path, default=CARPETA_ROSTROS)
    args = ap.parse_args(argv)
    base = rutas_por_defecto(args.data_dir).base
    existentes = copias(base)
    if args.listar or not args.copia:
        for c in existentes:
            n = len(list(c.glob("*.csv")))
            print(
                f"{c.name}  ({n} CSV{', con rostros' if (c / SUBCARPETA_ROSTROS).is_dir() else ''})"
            )
        if not existentes:
            print("No hay copias en", base / CARPETA)
        return 0
    elegida = (
        existentes[-1]
        if args.copia == "ultimo" and existentes
        else base / CARPETA / args.copia
    )
    if not elegida.is_dir():
        print(f"No existe la copia {elegida}", file=sys.stderr)
        return 1
    for nombre, resultado in restaurar(elegida, base, args.rostros):
        print(f"{nombre}: {resultado}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
