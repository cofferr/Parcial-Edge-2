"""Tarea 1.4: tprop con ping del sistema, RTT por connect TCP, línea base y d/v.

    uv run python scripts/t1_4_tprop.py                # en reposo (≥100 muestras)
    uv run python scripts/t1_4_tprop.py --carga        # además RTT bajo carga (aparte)

Precondición: ninguna fuente transmitiendo (stream de la ESP32 cerrado), ninguna otra app
usando la red. `ping -i 0.2` (macOS: <0,002 s solo con root). 100 muestras ≈ 20 s por destino.
El RTT bajo carga se reporta aparte y nunca entra en la fórmula de tprop.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from edge_parcial.analysis.tprop import cargar_tprop, resumen_tprop
from edge_parcial.config import RAIZ, RUTA_CONFIG, ErrorConfig, cargar_config
from edge_parcial.tprop import medir_tprop


def imprimir(resumen) -> None:
    print("\n== tprop (ms) ==")
    for _, r in resumen.iterrows():
        if r["fuente"] == "local":
            print("local: sin enlace de red, tprop = 0")
            continue
        suf = "" if r.get("muestras_icmp_suficientes") else "  [<100 muestras ICMP]"
        print(
            f"{r['fuente']:9s} RTT ICMP media {r['rtt_icmp_ms_media']:.3f} ms -> tprop = RTT/2 = "
            f"{r['tprop_icmp_ms_media']:.3f} ms (p50 {r['tprop_icmp_ms_p50']:.3f}, p95 "
            f"{r['tprop_icmp_ms_p95']:.3f}, n={r['rtt_icmp_ms_n']}){suf}"
        )
        if "rtt_tcp_ms_media" in r and r["rtt_tcp_ms_n"]:
            print(
                f"{'':9s} contraste TCP connect: RTT media {r['rtt_tcp_ms_media']:.3f} ms (n={r['rtt_tcp_ms_n']})"
            )
        if "tprop_fisico_ns" in r:
            print(
                f"{'':9s} d/v físico: {r['tprop_fisico_ns']:.2f} ns (d = {r['distancia_m']} m)"
            )
        if r.get("rtt_carga_ms_n"):
            print(
                f"{'':9s} RTT bajo carga (APARTE, fuera de la fórmula): media {r['rtt_carga_ms_media']:.3f} ms"
            )


def main(argv: list[str] | None = None, *, ejecutor=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument(
        "--n", type=int, default=100, help="muestras por método y destino (≥100)"
    )
    ap.add_argument("--intervalo-s", type=float, default=0.2)
    ap.add_argument("--pausa-tcp-s", type=float, default=0.05)
    ap.add_argument(
        "--carga", action="store_true", help="medir también el RTT bajo carga (aparte)"
    )
    ap.add_argument("--fuentes", default="esp32,droidcam,local")
    ap.add_argument("--config", type=Path, default=RUTA_CONFIG)
    ap.add_argument("--salida", type=Path, default=RAIZ / "data" / "raw")
    ap.add_argument("--cpu-s", type=float, default=2.0)
    args = ap.parse_args(argv)
    try:
        cfg = cargar_config(args.config)
    except ErrorConfig as e:
        print(f"Error de configuración: {e}", file=sys.stderr)
        return 2
    fuentes = tuple(f.strip() for f in args.fuentes.split(",") if f.strip())
    if set(fuentes) - {"esp32", "droidcam", "local"}:
        print(f"Fuentes inválidas: {args.fuentes}", file=sys.stderr)
        return 2
    if args.n < 100:
        print(f"AVISO: {args.n} muestras < 100: el tprop no será concluyente.")
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-tprop"
    kw = {"ejecutor": ejecutor} if ejecutor else {}
    meta = medir_tprop(
        cfg, run_id, args.salida, fuentes=fuentes, n=args.n, intervalo_s=args.intervalo_s, pausa_tcp_s=args.pausa_tcp_s,
        carga=args.carga, cpu_s=args.cpu_s, **kw,
    )  # fmt: skip
    imprimir(resumen_tprop(cargar_tprop(args.salida / run_id), cfg))
    print(f"\nDatos crudos: {args.salida / run_id}  (válida: {meta['valida']})")
    for m in meta["motivos_invalida"]:
        print(f"INVÁLIDA: {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
