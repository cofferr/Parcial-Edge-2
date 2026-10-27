"""Tarea 1.6: grabación guiada de las tres fuentes (escena estática / con actividad).

    uv run python scripts/t1_6_grabar.py --confirmo-efectos-desactivados

Guion por defecto: 60 s estáticos (calibración) + 5 ciclos de 15 s quieto / 15 s con
actividad. Sigue las indicaciones de la ventana. Salida en data/recordings/<run_id>/
(contiene rostros: fuera de git). Pulsa q para abortar.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from edge_parcial.acquisition.grabador import ejecutar_grabacion, guion_estandar
from edge_parcial.acquisition.pantalla import PantallaCV2
from edge_parcial.config import RAIZ, RUTA_CONFIG, ErrorConfig, cargar_config

FUENTES = ("local", "esp32", "droidcam")


def main(argv: list[str] | None = None, *, camara_factory=None, pantalla=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--calibracion-s", type=float, default=60.0)
    ap.add_argument("--ciclos", type=int, default=5)
    ap.add_argument("--estatico-s", type=float, default=15.0)
    ap.add_argument("--actividad-s", type=float, default=15.0)
    ap.add_argument("--fuentes", default=",".join(FUENTES))
    ap.add_argument("--config", type=Path, default=RUTA_CONFIG)
    ap.add_argument("--salida", type=Path, default=RAIZ / "data" / "recordings")
    ap.add_argument("--cpu-s", type=float, default=2.0)
    ap.add_argument("--confirmo-efectos-desactivados", action="store_true")
    args = ap.parse_args(argv)
    fuentes = tuple(f.strip() for f in args.fuentes.split(",") if f.strip())
    if not fuentes or set(fuentes) - set(FUENTES):
        print(f"Fuentes inválidas: {args.fuentes}", file=sys.stderr)
        return 2
    try:
        cfg = cargar_config(args.config)
    except ErrorConfig as e:
        print(f"Error de configuración: {e}", file=sys.stderr)
        return 2
    guion = guion_estandar(
        args.calibracion_s, args.ciclos, args.estatico_s, args.actividad_s
    )
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-grabacion"
    kw = {"camara_factory": camara_factory} if camara_factory else {}
    meta = ejecutar_grabacion(
        cfg, run_id, fuentes, guion, args.salida, pantalla or PantallaCV2(),
        efectos_confirmados=args.confirmo_efectos_desactivados, cpu_s=args.cpu_s, **kw,
    )  # fmt: skip
    print(
        f"{run_id}: {'válida' if meta['valida'] else 'INVÁLIDA: ' + '; '.join(meta['motivos_invalida'])}"
    )
    return 0 if meta["valida"] else 1


if __name__ == "__main__":
    sys.exit(main())
