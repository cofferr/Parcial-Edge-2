"""Tarea 2.2: calibra y evalúa el detector de movimiento con una grabación existente.

    uv run python scripts/t2_2_calibrar.py                      # última grabación de data/recordings
    uv run python scripts/t2_2_calibrar.py --escribir-config    # además escribe [detector.*] en config.toml

Sin hardware: usa los JPEG de data/recordings/<run_id>/. T_pix y T_area salen de los 60 s
estáticos; umbral_voto deja <= 1 % de ventanas estáticas con voto True; después se evalúa
en los 150 s guionizados (docs/DISENO.md §23). Salidas en data/processed/t2_2_*.
"""

import argparse
import sys
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd

from edge_parcial.analysis.tablas import escribir_tabla
from edge_parcial.config import RAIZ, RUTA_CONFIG
from edge_parcial.edge import calibracion as cal
from edge_parcial.edge.detector import ParamsDetector
from edge_parcial.fog.quorum import quorum
from edge_parcial.nucleo.config_p2 import (
    FUENTES,
    escribir_secciones_detector,
    texto_secciones_detector,
)


def ultima_grabacion(base: Path) -> Path:
    carpetas = sorted(p for p in base.glob("*-grabacion") if (p / "segmentos.csv").is_file())  # fmt: skip
    if not carpetas:
        raise SystemExit(f"No hay grabaciones con segmentos.csv en {base}")
    return carpetas[-1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)  # fmt: skip
    ap.add_argument("--grabacion", type=Path)
    ap.add_argument("--config", type=Path, default=RUTA_CONFIG)
    ap.add_argument("--salida", type=Path, default=RAIZ / "data" / "processed")
    ap.add_argument("--guarda-s", type=float, default=cal.GUARDA_S_DEFECTO)
    ap.add_argument(
        "--guarda-calibracion-s", type=float, default=cal.GUARDA_CALIBRACION_S
    )
    ap.add_argument("--escribir-config", action="store_true")
    args = ap.parse_args(argv)

    carpeta = args.grabacion or ultima_grabacion(RAIZ / "data" / "recordings")
    with open(args.config, "rb") as f:
        datos = tomllib.load(f)
    if "n" not in datos.get("quorum", {}):
        print("Falta [quorum] n en la config", file=sys.stderr)
        return 2
    n = int(datos["quorum"]["n"])
    ventana_s = float(datos["quorum"].get("ventana_s", 1.0))
    q = quorum(n)
    segmentos = pd.read_csv(carpeta / "segmentos.csv")
    calib = segmentos[segmentos["tipo"] == "calibracion"]
    ini, fin = int(calib["t_ini_ns"].min()), int(calib["t_fin_ns"].max())
    print(f"Grabación {carpeta.name}; N = {n}, Q = {q}")

    base = ParamsDetector(t_pix=1.0, t_area=0.0)
    params, diags, resultados = {}, [], {}
    for f in FUENTES:
        print(f"[{f}] cargando fotogramas...", flush=True)
        seq = cal.cargar_fuente(carpeta, f, base.tam)
        params[f], diag = cal.calibrar_fuente(
            seq, ini, fin, base, ventana_s, guarda_s=args.guarda_calibracion_s
        )
        diags.append(diag)
        resultados[f] = cal.reproducir(seq, params[f])
        print(f"[{f}] {diag}")

    ventanas = cal.evaluar(resultados, params, segmentos, q, ventana_s, args.guarda_s)
    filas = []
    for f in (*FUENTES, "quorum"):
        col = "alerta" if f == "quorum" else f"voto_{f}"
        m = cal.matriz_confusion(ventanas, col)
        extra = {}
        if f != "quorum":
            r = resultados[f]
            extra = {
                "fotogramas": len(r),
                "cambio_global": sum(x.cambio_global for x in r),
                "tapada": sum(x.tapada for x in r),
            }
        filas.append({"fuente": f, **m, **extra})
    evaluacion = pd.DataFrame(filas)

    args.salida.mkdir(parents=True, exist_ok=True)
    escribir_tabla(
        pd.DataFrame(diags), args.salida / "t2_2_calibracion",
        caption="Calibración del detector (60 s estáticos)", label="tab:t2_2_cal", decimales=4,
    )  # fmt: skip
    escribir_tabla(
        evaluacion, args.salida / "t2_2_evaluacion",
        caption="Evaluación por ventana de 1 s en los 150 s guionizados", label="tab:t2_2_eval",
        decimales=3,
    )  # fmt: skip
    ventanas.to_csv(args.salida / "t2_2_ventanas.csv", index=False)
    (args.salida / "t2_2_parametros.toml").write_text(texto_secciones_detector(params), encoding="utf-8")  # fmt: skip
    print(evaluacion.to_string(index=False))
    if args.escribir_config:
        escribir_secciones_detector(args.config, params)
        print(f"[detector.*] escrito en {args.config}")
    return 0 if np.isfinite(evaluacion["aciertos"]).all() else 1


if __name__ == "__main__":
    sys.exit(main())
