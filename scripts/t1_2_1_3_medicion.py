"""Tareas 1.2 y 1.3: corridas de medición de tamaño y tiempo de transmisión.

    uv run python scripts/t1_2_1_3_medicion.py --modo aislada     --corridas 5 --n 300
    uv run python scripts/t1_2_1_3_medicion.py --modo concurrente --corridas 5 --n 300 \\
        --confirmo-efectos-desactivados

Por fuente: 20 fotogramas de calentamiento (warmup=1) + N medidos. CSV crudo sin
redondear en data/raw/<run_id>/. Las tablas oficiales usan la corrida 1 (ver
scripts/t1_2_1_3_tablas.py). Sin --confirmo-efectos-desactivados la fuente local queda
valida:false. La ESP32-CAM admite UN solo cliente: cierra navegador y otras corridas.
"""

import argparse
import sys
from pathlib import Path

from edge_parcial.config import RAIZ, RUTA_CONFIG, ErrorConfig, cargar_config
from edge_parcial.medicion import FUENTES, MODOS, ejecutar_medicion


def main(argv: list[str] | None = None, *, camara_factory=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--modo", required=True, choices=MODOS)
    ap.add_argument("--corridas", type=int, default=5)
    ap.add_argument(
        "--n", type=int, default=300, help="fotogramas medidos por fuente y corrida"
    )
    ap.add_argument("--fuentes", default=",".join(FUENTES))
    ap.add_argument("--config", type=Path, default=RUTA_CONFIG)
    ap.add_argument("--salida", type=Path, default=RAIZ / "data" / "raw")
    ap.add_argument("--pausa-s", type=float, default=2.0, help="pausa entre unidades")
    ap.add_argument(
        "--cpu-s", type=float, default=2.0, help="duración del muestreo de CPU"
    )
    ap.add_argument("--timeout-s", type=float, default=1800.0)
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
    kw = {"camara_factory": camara_factory} if camara_factory else {}
    metas = ejecutar_medicion(
        cfg, args.modo, args.corridas, args.n, fuentes, args.salida,
        pausa_s=args.pausa_s, cpu_s=args.cpu_s, timeout_s=args.timeout_s,
        efectos_confirmados=args.confirmo_efectos_desactivados, **kw,
    )  # fmt: skip
    invalidas = [m["run_id"] for m in metas if not m["valida"]]
    print(f"\n{len(metas)} unidades; inválidas: {len(invalidas)}")
    for r in invalidas:
        print(f"  - {r}")
    print("Siguiente: uv run python scripts/t1_2_1_3_tablas.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
