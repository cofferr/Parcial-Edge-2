"""Desglose del e2e (Tarea 1.5), arranque de DroidCam y tabla del Reto experto 1.

    uv run python scripts/t1_5_desglose.py [--lmax-ms 100] [--raw data/raw] [--salida data/processed/tablas]

Solo usa datos ya medidos en data/raw (no mide de nuevo). CSV sin redondear y LaTeX redondeado.
"""

import argparse
import sys
from pathlib import Path

from edge_parcial.analysis.carga import cargar_corridas
from edge_parcial.analysis.desglose_e2e import (
    arranque_droidcam,
    desglose_esp32,
    tabla_reto1,
    ultima_utilizable,
    velocidad_efectiva_esp32,
)
from edge_parcial.analysis.tablas import escribir_tabla
from edge_parcial.analysis.tprop import elegir_tprop
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
    ap.add_argument("--lmax-ms", type=float, required=True, help="Lmax del Reto 1 (ms)")
    args = ap.parse_args(argv)
    try:
        cfg = cargar_config(args.config)
    except ErrorConfig as e:
        print(f"Error de configuración: {e}", file=sys.stderr)
        return 2
    corridas = cargar_corridas(args.raw)
    tprop_res, _ = elegir_tprop(args.raw, cfg)
    if tprop_res is None:
        print("No hay corrida de tprop válida", file=sys.stderr)
        return 1
    e_esp = ultima_utilizable(corridas, "1.5", "esp32")
    e_dc = ultima_utilizable(corridas, "1.5", "droidcam")
    r_dc = ultima_utilizable(corridas, "1.2_1.3", "droidcam", "aislada")
    tablas = {"t1_5_desglose_esp32": (desglose_esp32(e_esp, cfg, tprop_res), "Desglose del e2e de la ESP32 (/capture), ms")}  # fmt: skip
    tablas["t1_5_velocidad_efectiva_esp32"] = (velocidad_efectiva_esp32(e_esp, cfg), "Velocidad efectiva de la ESP32 (/capture) con las dos coberturas del ttx")  # fmt: skip
    if e_dc and r_dc:
        tablas["t1_5_arranque_droidcam"] = (arranque_droidcam(e_dc, r_dc), "Arranque y e2e de DroidCam frente al régimen estable, ms")  # fmt: skip
    tablas["reto1_latencia"] = (tabla_reto1(corridas, args.lmax_ms), f"Reto experto 1: L por fuente (ms), Lmax = {args.lmax_ms:g} ms, cumple con p95")  # fmt: skip
    for nombre, (df, caption) in tablas.items():
        escribir_tabla(
            df,
            args.salida / nombre,
            caption=caption,
            label=f"tab:{nombre}",
            decimales=3,
        )
        print(
            f"\n{nombre}\n{df.to_string(index=False, float_format=lambda x: f'{x:.3f}')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
