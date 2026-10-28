"""Punto de entrada: `uv run python -m edge_parcial.ble`."""

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from edge_parcial.ble.gateway import FuenteBleak, Gateway, ParamsBle
from edge_parcial.ble.telemetria import EscritorTelemetria


async def _principal(args: argparse.Namespace) -> None:
    params = ParamsBle()
    gw = Gateway(FuenteBleak(params), EscritorTelemetria(args.csv), args.estado, params)
    bucle = asyncio.get_running_loop()
    for senal in (signal.SIGINT, signal.SIGTERM):
        bucle.add_signal_handler(senal, gw.detener)
    await gw.ejecutar()


def main() -> None:
    ap = argparse.ArgumentParser(description="Gateway BLE -> telemetria.csv")
    ap.add_argument("--csv", type=Path, default=Path("data/telemetria.csv"))
    ap.add_argument("--estado", type=Path, default=Path("data/estado.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(_principal(args))


if __name__ == "__main__":
    main()
