"""Tarea 2.2: curva de compromiso aciertos / falsos positivos de la ESP32-CAM (docs/DISENO.md §23).

    uv run python scripts/t2_2_barrido_esp32.py

Con la grabación guionizada barre T_area, umbral_voto y un mínimo de fotogramas evaluados por
ventana (por debajo, el voto es False). Los otros dos votos quedan con los parámetros de
config.toml, para ver también el efecto sobre el quórum. Ojo: el barrido usa las mismas
ventanas con las que se evalúa, así que la mejor fila es optimista. No escribe config.toml.
Salida: data/processed/t2_2_barrido_esp32.{csv,tex}.
"""

import argparse
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

import pandas as pd

from edge_parcial.analysis.tablas import escribir_tabla
from edge_parcial.config import RAIZ, RUTA_CONFIG
from edge_parcial.edge import calibracion as cal
from edge_parcial.edge.detector import votar
from edge_parcial.fog.quorum import quorum
from edge_parcial.nucleo.config_p2 import FUENTES, params_detector

T_AREA_X = (1, 2, 3, 5, 8)  # múltiplos del T_area calibrado
UMBRALES = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7)
MIN_FOTOGRAMAS = (1, 2, 3)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)  # fmt: skip
    ap.add_argument("--grabacion", type=Path)
    ap.add_argument("--config", type=Path, default=RUTA_CONFIG)
    ap.add_argument("--salida", type=Path, default=RAIZ / "data" / "processed")
    args = ap.parse_args(argv)

    carpeta = args.grabacion or max((RAIZ / "data" / "recordings").glob("*-grabacion"))
    with open(args.config, "rb") as f:
        datos = tomllib.load(f)
    q = quorum(int(datos["quorum"]["n"]))
    params = {f: params_detector(datos, f) for f in FUENTES}
    segmentos = pd.read_csv(carpeta / "segmentos.csv")
    resultados = {}
    for f in FUENTES:
        print(f"[{f}] cargando fotogramas...", flush=True)
        seq = cal.cargar_fuente(carpeta, f, params[f].tam)
        resultados[f] = cal.reproducir(seq, params[f])

    ventana_ns = int(1e9)
    t0 = int(segmentos["t_ini_ns"].min())
    n_v = (int(segmentos["t_fin_ns"].max()) - t0) // ventana_ns
    cubos_otros = {
        f: cal._agrupar(resultados[f], t0, ventana_ns, n_v) for f in FUENTES[1:]
    }
    etiquetas = [cal.etiqueta_ventana(t0 + k * ventana_ns, t0 + (k + 1) * ventana_ns, segmentos, 1.0) for k in range(n_v)]  # fmt: skip
    votos_otros = {
        f: [votar(c, params[f].umbral_voto)[0] for c in cubos_otros[f]]
        for f in cubos_otros
    }

    filas = []
    for x in T_AREA_X:
        p = replace(params["esp32"], t_area=params["esp32"].t_area * x)
        cubos = cal._agrupar(cal.reproducir(cal.cargar_fuente(carpeta, "esp32", p.tam), p), t0, ventana_ns, n_v)  # fmt: skip
        for umbral in UMBRALES:
            for minimo in MIN_FOTOGRAMAS:
                voto = [
                    sum(r.evaluado for r in c) >= minimo and votar(c, umbral)[0]
                    for c in cubos
                ]
                v = pd.DataFrame(
                    {
                        "ventana": range(n_v), "tipo": etiquetas, "voto_esp32": voto,
                        **{f"voto_{f}": votos_otros[f] for f in votos_otros},
                    }
                )  # fmt: skip
                v["alerta"] = v[[f"voto_{f}" for f in FUENTES]].sum(axis=1) >= q
                m, mq = (
                    cal.matriz_confusion(v, "voto_esp32"),
                    cal.matriz_confusion(v, "alerta"),
                )
                filas.append(
                    {
                        "t_area_x": x, "t_area": p.t_area, "umbral_voto": umbral,
                        "min_fotogramas": minimo, "tasa_VP": m["tasa_VP"], "FP": m["FP"],
                        "tasa_FP": m["tasa_FP"], "aciertos": m["aciertos"],
                        "quorum_aciertos": mq["aciertos"], "quorum_FP": mq["FP"],
                    }
                )  # fmt: skip
    tabla = pd.DataFrame(filas).sort_values(["FP", "tasa_VP"], ascending=[True, False])
    escribir_tabla(
        tabla, args.salida / "t2_2_barrido_esp32",
        caption="Compromiso aciertos/falsos positivos de la ESP32-CAM (ventanas de 1 s)",
        label="tab:t2_2_barrido", decimales=3,
    )  # fmt: skip
    pd.set_option("display.width", 200)
    print("Hay que elegir entre sensibilidad y FP; 0 y 1 FP de 65 ventanas estáticas:")
    print(tabla[tabla["FP"] <= 1].head(12).to_string(index=False))
    actual = tabla[(tabla["t_area_x"] == 1) & (tabla["umbral_voto"] == params["esp32"].umbral_voto) & (tabla["min_fotogramas"] == 1)]  # fmt: skip
    print("Parámetros actuales:")
    print(actual.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
