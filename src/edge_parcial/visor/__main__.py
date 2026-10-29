"""Punto de entrada: `uv run python -m edge_parcial.visor` (solo 127.0.0.1)."""

import argparse
import logging

import uvicorn

from edge_parcial.visor.servidor import HOST, PUERTO, crear_app


def main() -> None:
    ap = argparse.ArgumentParser(description="Visor MJPEG de las tres fuentes")
    ap.add_argument("--puerto", type=int, default=PUERTO)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    uvicorn.run(crear_app(), host=HOST, port=args.puerto, log_level="warning")


if __name__ == "__main__":
    main()
