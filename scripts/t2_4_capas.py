"""Tarea 2.4: latencia por capas (device / edge / fog) con las tres fuentes, 5 min.

    uv run python scripts/t2_4_capas.py --confirmo-efectos-desactivados --ventanas
    uv run python scripts/t2_4_capas.py --analizar data/raw/<run_id>     # solo el análisis

Actividad alternada: ciclos de `--ciclo-s` s quieto / `--ciclo-s` s con movimiento frente a las
tres cámaras (sigue el texto de la consola). Crudo por fotograma y por ventana en
data/raw/<run_id>/capas_*.csv; tablas CSV y LaTeX en data/processed/t2_4_*
(docs/DISENO.md §25). Las capas son módulos lógicos de un mismo proceso: no hay red entre ellas.
La ESP32-CAM admite un solo cliente: nada más debe estar conectado a ella.
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path
from time import perf_counter_ns

import numpy as np

from edge_parcial import metadata
from edge_parcial.acquisition.pantalla import PantallaCV2
from edge_parcial.capas import analisis
from edge_parcial.capas.registro import RegistroCapas
from edge_parcial.config import RAIZ, RUTA_CONFIG, ErrorConfig
from edge_parcial.nucleo import prueba_quorum as pq
from edge_parcial.nucleo.config_p2 import FUENTES, cargar_config_p2
from edge_parcial.nucleo.fuentes import EntradaSimulada, construir_entradas
from edge_parcial.nucleo.nucleo import Nucleo

INDICACION = {
    "quieto": "QUIETO: no te muevas ni muevas nada frente a las cámaras.",
    "actividad": "ACTIVIDAD: MUÉVETE frente a las tres cámaras.",
}


def entradas_simuladas() -> dict:
    """Fuentes sintéticas con distinto retardo de device (para ensayar el análisis)."""

    def g(t_s):
        img = np.full((240, 320), 120, np.uint8)
        x = int(t_s * 200) % 200
        img[60:120, x : x + 60] = 250
        return img

    retardos = {"esp32": 0.04, "droidcam": 0.01, "local": 0.0}
    return {
        f: EntradaSimulada(f, g, fps=20, retardo_device_s=retardos[f]) for f in FUENTES
    }


def main(argv: list[str] | None = None, *, pantalla=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--duracion-s", type=float, default=300.0)
    ap.add_argument("--ciclo-s", type=float, default=15.0)
    ap.add_argument("--calentamiento-s", type=float, default=5.0)
    ap.add_argument("--ventanas", action="store_true")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--analizar", type=Path, help="solo analiza una corrida existente")
    ap.add_argument("--confirmo-efectos-desactivados", action="store_true")
    ap.add_argument("--config", type=Path, default=RUTA_CONFIG)
    ap.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw")
    ap.add_argument("--salida", type=Path, default=RAIZ / "data" / "processed")
    args = ap.parse_args(argv)

    if args.analizar:
        print(analisis.escribir_tablas(args.analizar, args.salida))
        return 0
    try:
        cfg = cargar_config_p2(args.config)
    except ErrorConfig as e:
        print(f"Error de configuración: {e}", file=sys.stderr)
        return 2
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-capas" + ("-sim" if args.simular else "")
    carpeta = args.raw / run_id
    carpeta.mkdir(parents=True)
    meta = None
    if not args.simular:
        meta = metadata.recolectar_metadata(
            cfg.base, run_id, fuentes=FUENTES,
            efectos_confirmados=args.confirmo_efectos_desactivados,
            contexto={"tarea": "2.4", "duracion_s": args.duracion_s, "ciclo_s": args.ciclo_s},
        )  # fmt: skip
        if not meta["esp32_status_inicio"]["ok"]:
            print(
                f"La ESP32-CAM no responde: {meta['esp32_status_inicio']['error']}",
                file=sys.stderr,
            )
            return 3
    entradas = entradas_simuladas() if args.simular else construir_entradas(cfg.base)
    nucleo = Nucleo(
        cfg, entradas, run_id, carpeta / "eventos.csv", carpeta / "estado.json",
        capas=RegistroCapas(carpeta),
    )  # fmt: skip
    pantalla = (pantalla or PantallaCV2()) if args.ventanas else None
    segmentos = []
    try:
        nucleo.iniciar()
        print(f"Calentamiento ({args.calentamiento_s:.0f} s)...")
        pq.esperar(args.calentamiento_s, pantalla, nucleo, lambda s: None)
        fin = perf_counter_ns() + int(args.duracion_s * 1e9)
        tipo = "quieto"
        while perf_counter_ns() < fin:
            restante_s = (fin - perf_counter_ns()) / 1e9
            dur = min(args.ciclo_s, restante_s)
            print(
                f"\n>>> {INDICACION[tipo]}  ({dur:.0f} s; quedan {restante_s:.0f} s en total)"
            )
            t_ini = perf_counter_ns()
            pq.esperar(dur, pantalla, nucleo, lambda s: None)
            segmentos.append((tipo, t_ini, perf_counter_ns()))
            tipo = "actividad" if tipo == "quieto" else "quieto"
    except pq.PruebaAbortada:
        print("Corrida abortada con q: no se analiza.")
        return 1
    finally:
        nucleo.detener()
        if pantalla is not None:
            pantalla.cerrar()
    with open(carpeta / "segmentos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["run_id", "idx", "tipo", "t_ini_ns", "t_fin_ns"])
        for i, (tipo, a, b) in enumerate(segmentos):
            w.writerow([run_id, i, tipo, a, b])
    if meta is not None:
        for f in FUENTES:
            res = entradas[f].resumen()
            if f == "local":
                metadata.registrar_camara_local(
                    meta, entradas[f].propiedades_camara(), res
                )
            metadata.registrar_resumen_fuente(meta, f, res)
        metadata.cerrar_metadata(meta, cfg.base)
        metadata.escribir_metadata(meta, args.raw)
        if not meta["valida"]:
            print(
                "AVISO: corrida marcada inválida:", "; ".join(meta["motivos_invalida"])
            )
    resumen = analisis.escribir_tablas(carpeta, args.salida)
    print(resumen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
