"""Tarea 1.5: latencia extremo a extremo medida (petición -> fotograma disponible).

    uv run python scripts/t1_5_e2e.py --n 300 [--corridas 1]

- ESP32-CAM: /capture con conexión nueva por muestra.
- DroidCam: apertura del stream hasta el primer fotograma decodificado (o URL de imagen
  fija si `[droidcam].url_imagen_fija` está definida en la config).
- Local: read() con la cámara abierta (la apertura no cuenta).
Una fuente a la vez. Después: uv run python scripts/t1_5_analisis.py
"""

import argparse
import sys
from pathlib import Path

from edge_parcial.config import RAIZ, RUTA_CONFIG, ErrorConfig, cargar_config
from edge_parcial.medicion import FUENTES, ejecutar_e2e


def main(argv: list[str] | None = None, *, camara_factory=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--corridas", type=int, default=1)
    ap.add_argument("--fuentes", default=",".join(FUENTES))
    ap.add_argument("--config", type=Path, default=RUTA_CONFIG)
    ap.add_argument("--salida", type=Path, default=RAIZ / "data" / "raw")
    ap.add_argument("--pausa-s", type=float, default=2.0)
    ap.add_argument("--cpu-s", type=float, default=2.0)
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
    metas = ejecutar_e2e(
        cfg, args.corridas, args.n, fuentes, args.salida, pausa_s=args.pausa_s,
        cpu_s=args.cpu_s, timeout_s=args.timeout_s,
        efectos_confirmados=args.confirmo_efectos_desactivados, **kw,
    )  # fmt: skip
    invalidas = [m["run_id"] for m in metas if not m["valida"]]
    print(f"\n{len(metas)} unidades; inválidas: {len(invalidas)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
