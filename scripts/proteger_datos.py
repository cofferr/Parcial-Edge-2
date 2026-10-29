"""Protege (o desprotege) los datos medidos: data/raw y data/processed en solo lectura.

    uv run python scripts/proteger_datos.py              # bloquear (chmod a-w, recursivo)
    uv run python scripts/proteger_datos.py --estado     # ver si están bloqueados
    uv run python scripts/proteger_datos.py --desbloquear   # SOLO para regenerar tablas

Con la carpeta bloqueada no se puede borrar, renombrar ni crear nada dentro. Este script solo
cambia permisos: nunca borra ni mueve archivos. Tras regenerar, vuelve a bloquear.
"""

import argparse
import os
import stat
import sys
from pathlib import Path

from edge_parcial.config import RAIZ

PROTEGIDAS = ("data/raw", "data/processed")
ESCRITURA = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


def _recorrer(raiz: Path):
    yield raiz
    for dirpath, dirnames, filenames in os.walk(raiz):
        for nombre in (*dirnames, *filenames):
            yield Path(dirpath) / nombre


def bloquear(raiz: Path) -> int:
    n = 0
    # Primero los hijos y al final la propia carpeta (la raíz dejaría de ser recorrible).
    for ruta in reversed(list(_recorrer(raiz))):
        if ruta.is_symlink():
            continue
        modo = ruta.stat().st_mode
        if modo & ESCRITURA:
            ruta.chmod(modo & ~ESCRITURA)
            n += 1
    return n


def desbloquear(raiz: Path) -> int:
    n = 0
    for ruta in _recorrer(raiz):  # primero la carpeta, para poder recorrer lo de dentro
        if ruta.is_symlink():
            continue
        modo = ruta.stat().st_mode
        if not modo & stat.S_IWUSR:
            ruta.chmod(modo | stat.S_IWUSR)
            n += 1
    return n


def bloqueada(raiz: Path) -> bool:
    return not os.access(raiz, os.W_OK)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--desbloquear", action="store_true")
    ap.add_argument("--estado", action="store_true")
    ap.add_argument("--base", type=Path, default=RAIZ, help="raíz del repo (pruebas)")
    args = ap.parse_args(argv)
    rutas = [args.base / r for r in PROTEGIDAS if (args.base / r).is_dir()]
    if not rutas:
        print("No hay data/raw ni data/processed.", file=sys.stderr)
        return 1
    for r in rutas:
        if args.estado:
            print(
                f"{r.relative_to(args.base)}: {'BLOQUEADA (solo lectura)' if bloqueada(r) else 'editable'}"
            )
        elif args.desbloquear:
            print(
                f"{r.relative_to(args.base)}: desbloqueada ({desbloquear(r)} permisos cambiados)"
            )
        else:
            print(
                f"{r.relative_to(args.base)}: bloqueada ({bloquear(r)} permisos cambiados)"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
