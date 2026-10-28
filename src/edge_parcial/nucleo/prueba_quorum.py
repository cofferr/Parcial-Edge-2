"""Prueba física guiada del quórum (Tarea 2.3): tres fases con cuenta atrás.

- Fase A: las tres cámaras libres y con movimiento -> debe haber alerta.
- Fase B: una cámara tapada y las otras dos con movimiento -> debe haber alerta.
- Fase C: dos cámaras tapadas y la tercera con movimiento -> NO debe haber alerta.

Se resume por fase (ventanas, votos True por fuente, alertas) a partir de eventos.csv.
Se descartan los primeros `guarda_s` de cada fase (tiempo de tapar/destapar y de que el
voto se estabilice) y las ventanas que no caen enteras dentro de la fase.
"""

import csv
import time
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter_ns

import pandas as pd

from edge_parcial.acquisition.pantalla import Pantalla
from edge_parcial.nucleo.nucleo import Nucleo
from edge_parcial.nucleo.salidas import FUENTES
from edge_parcial.nucleo.ventanas import ejecutar_ventanas

GUARDA_S_DEFECTO = 4.0


class PruebaAbortada(Exception):
    """El usuario pulsó q durante la prueba."""


@dataclass(frozen=True)
class Fase:
    nombre: str
    descripcion: str
    tapadas: tuple[str, ...]
    debe_alertar: bool

    def instruccion(self) -> str:
        libres = [f for f in FUENTES if f not in self.tapadas]
        if not self.tapadas:
            return "NO tapes ninguna cámara y MUÉVETE frente a las tres."
        return (
            f"TAPA la cámara {' y la cámara '.join(self.tapadas)} (con la mano o un objeto opaco, "
            f"sin moverlas) y MUÉVETE frente a {' y '.join(libres)}."
        )


def fases_por_defecto(tapa_b=("esp32",), tapa_c=("esp32", "droidcam")) -> list[Fase]:
    return [
        Fase("A", "todas libres con movimiento", (), True),
        Fase(
            "B",
            f"una tapada ({', '.join(tapa_b)}) y las otras dos con movimiento",
            tuple(tapa_b),
            True,
        ),
        Fase(
            "C",
            f"dos tapadas ({', '.join(tapa_c)}) y la tercera con movimiento",
            tuple(tapa_c),
            False,
        ),
    ]


def resumir_fases(
    eventos: pd.DataFrame, tiempos: list[dict], guarda_s: float, ventana_s: float
) -> pd.DataFrame:
    """Una fila por fase: ventanas, votos True por fuente, alertas y si cumple lo esperado."""
    filas = []
    ventana_ns = int(ventana_s * 1e9)
    for t in tiempos:
        ini = t["t_ini_ns"] + int(guarda_s * 1e9)
        fin = t["t_fin_ns"]
        e = eventos[(eventos["t_ventana_ini_ns"] >= ini) & (eventos["t_ventana_ini_ns"] + ventana_ns <= fin)]  # fmt: skip
        n = len(e)
        alertas = int(e["alerta"].sum())
        fila = {
            "fase": t["fase"], "descripcion": t["descripcion"],
            "tapadas": ",".join(t["tapadas"]) or "ninguna",
            "ventanas": n, "alertas": alertas,
            "fraccion_alertas": alertas / n if n else float("nan"),
        }  # fmt: skip
        for f in FUENTES:
            fila[f"votos_true_{f}"] = int(e[f"voto_{f}"].sum())
        fila["esperado"] = "alerta" if t["debe_alertar"] else "sin alerta"
        # A y B: debe haber alerta (al menos una ventana); C: ninguna.
        fila["cumple"] = bool(n > 0 and ((alertas > 0) if t["debe_alertar"] else (alertas == 0)))  # fmt: skip
        filas.append(fila)
    return pd.DataFrame(filas)


def leer_eventos(ruta: Path, run_id: str) -> pd.DataFrame:
    with open(ruta, encoding="utf-8", newline="") as f:
        filas = [r for r in csv.DictReader(f) if r["run_id"] == run_id]
    df = pd.DataFrame(filas)
    if df.empty:
        return df
    for c in ("ventana", "t_ventana_ini_ns", "Q", "n_true", "alerta", *[f"voto_{f}" for f in FUENTES]):  # fmt: skip
        df[c] = df[c].astype(int)
    return df


def _espera(segundos: float, pantalla: Pantalla | None, nucleo: Nucleo, tick) -> None:
    """Espera `segundos` llamando a tick(restante_s) una vez por segundo; con `pantalla`
    dibuja las ventanas (hilo principal)."""
    fin = time.monotonic() + segundos
    ultimo = [None]

    def parar() -> bool:
        resto = fin - time.monotonic()
        entero = int(resto) + 1
        if resto > 0 and entero != ultimo[0]:
            ultimo[0] = entero
            tick(entero)
        return resto <= 0

    if pantalla is not None:
        if ejecutar_ventanas(nucleo, pantalla, parar=parar) == "tecla q":
            raise PruebaAbortada("prueba abortada con q")
        # si el usuario cerró una ventana, se sigue esperando sin dibujar
        while not parar():
            time.sleep(0.05)
    else:
        while not parar():
            time.sleep(0.05)


def ejecutar_prueba(
    nucleo: Nucleo,
    fases: list[Fase],
    *,
    pantalla: Pantalla | None,
    consola,
    cuenta_s: float = 10.0,
    fase_s: float = 40.0,
    calentamiento_s: float = 5.0,
    avisar=lambda fase: None,
) -> list[dict]:
    """Ejecuta las fases con el núcleo ya iniciado. Devuelve los tiempos de cada fase."""
    consola(f"Calentamiento ({calentamiento_s:.0f} s): las fuentes se estabilizan; NO tapes nada.")  # fmt: skip
    _espera(calentamiento_s, pantalla, nucleo, lambda s: None)
    tiempos = []
    for fase in fases:
        consola("")
        consola(f"=== FASE {fase.nombre}: {fase.descripcion} ===")
        consola(fase.instruccion())
        avisar(fase)
        _espera(cuenta_s, pantalla, nucleo, lambda s, n=fase.nombre: consola(f"  fase {n} empieza en {s} s..."))  # fmt: skip
        consola(f">>> FASE {fase.nombre}: ¡YA! ({fase_s:.0f} s)")
        t_ini = perf_counter_ns()
        _espera(fase_s, pantalla, nucleo, lambda s, n=fase.nombre: consola(f"  fase {n}: quedan {s} s") if s % 10 == 0 else None)  # fmt: skip
        tiempos.append({
            "fase": fase.nombre, "descripcion": fase.descripcion, "tapadas": fase.tapadas,
            "debe_alertar": fase.debe_alertar, "t_ini_ns": t_ini, "t_fin_ns": perf_counter_ns(),
        })  # fmt: skip
        consola(f"<<< FASE {fase.nombre} terminada.")
    return tiempos
