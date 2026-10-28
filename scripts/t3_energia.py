"""Parte 3, Tareas 3.1 a 3.3: energía de transmisión (ESP32-CAM) y latencia de DroidCam frente a 1 ms.

    uv run python scripts/t3_energia.py

Requiere en config.toml [energia]: e_elec_j_bit, e_fs_j_bit_m2, e_mp_j_bit_m4, cita y
`distancia_esp32_ap_m` (OBLIGATORIA, la da el autor: sin ella el script se niega a correr).
Lee las tablas de la Parte 1 de data/processed/tablas y data/processed. Salidas: t3_1_*, t3_1_energia_rx (complemento E_Rx), t3_2_*, t3_3_*
(CSV sin redondear y LaTeX redondeado). docs/DISENO.md §27.
"""

import argparse
import sys
from pathlib import Path

from edge_parcial.analysis import energia as en
from edge_parcial.analysis.tablas import escribir_tabla
from edge_parcial.config import RAIZ, RUTA_CONFIG

PROCESADO = RAIZ / "data" / "processed"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--config", type=Path, default=RUTA_CONFIG)
    ap.add_argument(
        "--tablas",
        type=Path,
        default=PROCESADO / "tablas",
        help="tablas de la Parte 1 (1.2, 1.3, Reto 1)",
    )
    ap.add_argument("--ahorro", type=Path, default=PROCESADO / "t1_6_ahorro.csv")
    ap.add_argument("--salida", type=Path, default=PROCESADO)
    args = ap.parse_args(argv)
    try:
        p = en.cargar_params(args.config)
        k = en.tamano_esp32_bits(args.tablas / "t1_2_tamano_aislada.csv")
        fps = en.fps_esp32(args.tablas / "t1_3_fps_aislada.csv")
        fracciones = en.fracciones_esp32(args.ahorro)
        t33 = en.tarea_3_3(args.tablas / "reto1_latencia.csv")
    except en.ErrorEnergia as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    t31 = en.tarea_3_1(p, k)
    t31_rx = en.tarea_3_1_rx(p, k)
    t32 = en.tarea_3_2(p, k["media"], fps, fracciones)
    escribir_tabla(
        t31.drop(columns=["razonamiento", "cita"]), args.salida / "t3_1_energia_fotograma",
        caption="Energía de transmisión por fotograma (ESP32-CAM)", label="tab:t3_1", decimales=9,
    )  # fmt: skip
    escribir_tabla(
        t31_rx, args.salida / "t3_1_energia_rx",
        caption="Complemento: energía de recepción E_Rx = k·E_elec (no entra en 3.1 ni en 3.2)", label="tab:t3_1_rx", decimales=9,
    )  # fmt: skip
    t31[["regimen", "razonamiento", "cita"]].drop_duplicates().to_csv(args.salida / "t3_1_regimen.csv", index=False)  # fmt: skip
    escribir_tabla(
        t32[
            [
                "p",
                "criterio_f",
                "f",
                "fotogramas_totales",
                "E_todos_J",
                "E_filtrado_J",
                "ahorro_J",
                "ahorro_pct",
            ]
        ],
        args.salida / "t3_2_ahorro_8h",
        caption="Energía de 8 h: todos los fotogramas frente a la fracción f",
        label="tab:t3_2",
        decimales=4,
    )
    t32.to_csv(args.salida / "t3_2_completo.csv", index=False)
    escribir_tabla(
        t33, args.salida / "t3_3_latencia_vs_1ms",
        caption="L medido de DroidCam frente a 1 ms", label="tab:t3_3", decimales=3,
    )  # fmt: skip
    print(f"Parámetros: {p}")
    print(f"k (bits): {k}; FPS = {fps}")
    print(t31[["k_tipo", "k_bits", "regimen", "E_Tx_J"]].to_string(index=False))
    print(t31_rx[["k_tipo", "k_bits", "E_Rx_J"]].to_string(index=False))
    print("Régimen:", t31.iloc[0]["razonamiento"])
    print(t32[["p", "criterio_f", "f", "E_todos_J", "E_filtrado_J", "ahorro_J", "ahorro_pct"]].to_string(index=False))  # fmt: skip
    print(t33[["caso", "estadistico", "L_medido_ms", "razon", "diferencia_ms"]].to_string(index=False))  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
