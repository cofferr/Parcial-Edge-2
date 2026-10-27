"""Figura de la Tarea 1.6: fracción transmitida f frente al umbral T_area.

Paleta categórica de la skill dataviz (azul, naranja, aqua; orden fijo por fuente),
superficie clara, rejilla recesiva, una sola escala en y (dos paneles, no doble eje),
leyenda siempre presente y estilos de línea distintos para no depender solo del color.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

SUPERFICIE = "#fcfcfb"
TINTA = "#1f1f1e"
TINTA_SUAVE = "#6b6b68"
REJILLA = "#e6e5e1"
COLORES = {"local": "#2a78d6", "esp32": "#eb6834", "droidcam": "#1baf7a"}
ESTILOS = {"local": "-", "esp32": "--", "droidcam": ":"}
MARCAS = {"local": "o", "esp32": "s", "droidcam": "^"}


def figura_f_vs_umbral(
    barrido: pd.DataFrame, elegidos: dict[str, float], ruta: Path | str
) -> Path:
    """Dos paneles (estático / actividad): f por fotogramas frente a T_area (eje x log)."""
    ruta = Path(ruta)
    fig, ejes = plt.subplots(1, 2, figsize=(9, 3.6), sharey=True, facecolor=SUPERFICIE)
    paneles = [
        ("f_frames_estatico", "Escena estática: fracción transmitida"),
        ("f_frames_actividad", "Con actividad: fracción transmitida"),
    ]
    for eje, (col, titulo) in zip(ejes, paneles, strict=True):
        eje.set_facecolor(SUPERFICIE)
        for fuente, g in barrido.groupby("fuente", sort=False):
            eje.plot(
                g["t_area"], g[col], color=COLORES[fuente], linestyle=ESTILOS[fuente],
                marker=MARCAS[fuente], markersize=4, linewidth=2, markevery=4,
                markeredgecolor=SUPERFICIE, label=fuente,
            )  # fmt: skip
            if fuente in elegidos:
                eje.axvline(
                    elegidos[fuente], color=COLORES[fuente], linewidth=1, alpha=0.5
                )
        if col.endswith("estatico"):
            eje.axhline(0.01, color=TINTA_SUAVE, linewidth=1, linestyle="-.")
        eje.set_xscale("log")
        eje.set_title(titulo, fontsize=10, color=TINTA, loc="left")
        eje.set_xlabel("T_area (fracción de píxeles)", color=TINTA_SUAVE, fontsize=9)
        eje.grid(True, color=REJILLA, linewidth=0.8)
        eje.set_axisbelow(True)
        for lado in ("top", "right"):
            eje.spines[lado].set_visible(False)
        for lado in ("left", "bottom"):
            eje.spines[lado].set_color(REJILLA)
        eje.tick_params(colors=TINTA_SUAVE, labelsize=8)
    ejes[0].set_ylabel(
        "f (fotogramas transmitidos / total)", color=TINTA_SUAVE, fontsize=9
    )
    ejes[0].set_ylim(-0.02, 1.02)
    ejes[1].legend(frameon=False, fontsize=8, labelcolor=TINTA, loc="upper right")
    fig.text(
        0.01, 0.01, "Líneas verticales: T_area elegido por fuente. Línea gris: límite de 1 % de estáticos transmitidos",
        fontsize=7.5, color=TINTA_SUAVE,
    )  # fmt: skip
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(ruta, dpi=160, facecolor=SUPERFICIE)
    plt.close(fig)
    return ruta
