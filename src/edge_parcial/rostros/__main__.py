"""Punto de entrada: `uv run python -m edge_parcial.rostros` (solo 127.0.0.1)."""

import argparse
import logging
from pathlib import Path

import uvicorn

from edge_parcial.rostros.reconocedor import CARPETA_ROSTROS, crear_reconocedor
from edge_parcial.rostros.servicio import HOST, PUERTO, crear_app


def _factor(texto: str) -> tuple[str, float]:
    fuente, _, valor = texto.partition("=")
    return fuente, float(valor)


def main() -> None:
    ap = argparse.ArgumentParser(description="Servicio HTTP de reconocimiento facial")
    ap.add_argument("--puerto", type=int, default=PUERTO)
    ap.add_argument("--rostros", type=Path, default=CARPETA_ROSTROS)
    ap.add_argument("--estado", type=Path, default=Path("data/estado.json"))
    ap.add_argument(
        "--factor", type=_factor, action="append", default=[], metavar="FUENTE=F"
    )
    ap.add_argument("--falso", action="store_true", help="reconocedor falso (sin dlib)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    reconocedor = crear_reconocedor(args.rostros, forzar_falso=args.falso)
    app = crear_app(reconocedor, dict(args.factor), args.estado)
    uvicorn.run(app, host=HOST, port=args.puerto, log_level="warning")


if __name__ == "__main__":
    main()
