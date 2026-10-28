"""Tarea 2.3: prueba física guiada del quórum (tres fases con cuenta atrás, ~40 s cada una).

    uv run python scripts/t2_3_prueba_quorum.py --ventanas

Fase A: todas libres con movimiento. Fase B: tapas una cámara y las otras dos con
movimiento (debe haber alerta). Fase C: tapas dos y la tercera con movimiento (no debe
haber alerta). Sigue el texto de la consola. `--ventanas` abre las tres cámaras con el
voto, el estado, Q, los votos True y el banner ALERTA (para capturas de pantalla); q aborta.

Antes de lanzarla: ESP32-CAM sin otros clientes abiertos, DroidCam en marcha y
[detector.*] calibrado en config.toml (scripts/t2_2_calibrar.py --escribir-config).
`--simular` ejecuta todo con fuentes sintéticas, sin hardware (ensayo).
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from edge_parcial import metadata
from edge_parcial.acquisition.pantalla import PantallaCV2
from edge_parcial.analysis.tablas import escribir_tabla
from edge_parcial.capas.registro import RegistroCapas
from edge_parcial.config import RAIZ, RUTA_CONFIG, ErrorConfig
from edge_parcial.nucleo import prueba_quorum as pq
from edge_parcial.nucleo.config_p2 import FUENTES, cargar_config_p2
from edge_parcial.nucleo.fuentes import EntradaSimulada, construir_entradas
from edge_parcial.nucleo.nucleo import Nucleo


def entradas_simuladas(tapadas: set[str]) -> dict:
    """Fuentes sintéticas: con movimiento salvo las que estén en `tapadas` (oscuras)."""

    def generador(nombre):
        def g(t_s):
            if nombre in tapadas:
                return np.full((240, 320), 4, np.uint8)
            img = np.full((240, 320), 120, np.uint8)
            x = int(t_s * 200) % 200
            img[60:120, x : x + 60] = 250
            return img

        return g

    return {f: EntradaSimulada(f, generador(f), fps=20) for f in FUENTES}


def escribir_resultados(resumen, run_id, args, log_ruta, salida, docs):
    pref = "t2_3_sim" if args.simular else "t2_3"
    escribir_tabla(
        resumen, salida / f"{pref}_resumen",
        caption="Prueba física del quórum: resumen por fase", label="tab:t2_3_resumen",
        decimales=3,
    )  # fmt: skip
    evid = docs / "evidencia"
    evid.mkdir(parents=True, exist_ok=True)
    copia = evid / f"{pref}_consola_{run_id}.log"
    shutil.copyfile(log_ruta, copia)
    filas = "\n".join(
        f"| {r.fase} | {r.descripcion} | {r.tapadas} | {r.ventanas} | {r.votos_true_esp32} | "
        f"{r.votos_true_droidcam} | {r.votos_true_local} | {r.alertas} | {r.esperado} | "
        f"{'sí' if r.cumple else '**NO**'} |"
        for r in resumen.itertuples()
    )
    md = f"""# Prueba física del quórum (Tarea 2.3){" [SIMULADA]" if args.simular else ""}

Corrida `{run_id}`. N = 3, Q = ⌊3/2⌋ + 1 = 2. Ventanas de 1 s sobre la rejilla común; se
descartan los primeros {args.guarda_s:g} s de cada fase y las ventanas que no caen enteras en ella.

| Fase | Descripción | Tapadas | Ventanas | Votos True esp32 | Votos True droidcam | Votos True local | Alertas | Esperado | Cumple |
|---|---|---|---|---|---|---|---|---|---|
{filas}

Registro de la consola (captura del log): `{copia.relative_to(docs.parent) if copia.is_relative_to(docs.parent) else copia}`.
Datos crudos: `data/raw/{run_id}/` (`eventos.csv`, `capas_ventanas.csv`, `consola.log`).
"""
    ruta = docs / f"{pref.upper()}_RESULTADOS.md"
    ruta.write_text(md, encoding="utf-8")
    return ruta


def main(argv: list[str] | None = None, *, pantalla=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)  # fmt: skip
    ap.add_argument("--ventanas", action="store_true", help="abre las tres cámaras con la superposición")  # fmt: skip
    ap.add_argument("--simular", action="store_true", help="fuentes sintéticas (sin hardware)")  # fmt: skip
    ap.add_argument("--fase-s", type=float, default=40.0)
    ap.add_argument("--cuenta-s", type=float, default=10.0)
    ap.add_argument("--calentamiento-s", type=float, default=5.0)
    ap.add_argument("--guarda-s", type=float, default=pq.GUARDA_S_DEFECTO)
    ap.add_argument("--tapa-b", default="esp32", help="fuentes tapadas en la fase B")
    ap.add_argument("--tapa-c", default="esp32,droidcam", help="fuentes tapadas en la fase C")  # fmt: skip
    ap.add_argument("--config", type=Path, default=RUTA_CONFIG)
    ap.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw")
    ap.add_argument("--salida", type=Path, default=RAIZ / "data" / "processed")
    ap.add_argument("--docs", type=Path, default=RAIZ / "docs")
    args = ap.parse_args(argv)
    tapa_b = tuple(s for s in args.tapa_b.split(",") if s)
    tapa_c = tuple(s for s in args.tapa_c.split(",") if s)
    if len(tapa_b) != 1 or len(tapa_c) != 2 or set(tapa_b + tapa_c) - set(FUENTES):
        print("--tapa-b debe tener 1 fuente y --tapa-c 2, entre esp32,droidcam,local", file=sys.stderr)  # fmt: skip
        return 2
    try:
        cfg = cargar_config_p2(args.config)
    except ErrorConfig as e:
        print(f"Error de configuración: {e}", file=sys.stderr)
        return 2

    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-quorum" + ("-sim" if args.simular else "")
    carpeta = args.raw / run_id
    carpeta.mkdir(parents=True)
    log_ruta = carpeta / "consola.log"
    log = open(log_ruta, "w", encoding="utf-8")  # noqa: SIM115 - se cierra en finally

    def consola(linea: str) -> None:
        print(linea, flush=True)
        log.write(linea + "\n")
        log.flush()

    fases = pq.fases_por_defecto(tapa_b, tapa_c)
    if args.simular:
        tapadas: set[str] = set()
        entradas = entradas_simuladas(tapadas)
        avisar = lambda fase: (tapadas.clear(), tapadas.update(fase.tapadas))
    else:
        entradas = construir_entradas(cfg.base)
        avisar = lambda fase: None
        status = metadata.consultar_status_esp32(
            cfg.base.esp32.ip, cfg.base.esp32.puerto
        )
        consola(f"/status ESP32 antes: {status}")
        if not status["ok"]:
            consola(
                "La ESP32-CAM no responde: abortado (ver docs/CHECKLIST_HARDWARE_P2.md)."
            )
            log.close()
            return 3
    # El cambio de fase de la simulación se aplica al empezar la cuenta atrás; en la
    # prueba real lo hace la persona al leer la instrucción.
    nucleo = Nucleo(
        cfg, entradas, run_id, carpeta / "eventos.csv", carpeta / "estado.json",
        capas=RegistroCapas(carpeta), consola=consola,
    )  # fmt: skip
    pantalla = (pantalla or PantallaCV2()) if args.ventanas else None
    estado, tiempos = 0, []
    try:
        nucleo.iniciar()
        tiempos = pq.ejecutar_prueba(
            nucleo, fases, pantalla=pantalla, consola=consola, cuenta_s=args.cuenta_s,
            fase_s=args.fase_s, calentamiento_s=args.calentamiento_s, avisar=avisar,
        )  # fmt: skip
    except pq.PruebaAbortada as e:
        consola(str(e))
        estado = 1
    finally:
        nucleo.detener()
        if pantalla is not None:
            pantalla.cerrar()
    if not args.simular:
        consola(f"/status ESP32 después: {metadata.consultar_status_esp32(cfg.base.esp32.ip, cfg.base.esp32.puerto)}")  # fmt: skip
    log.close()
    if estado:
        return estado
    eventos = pq.leer_eventos(carpeta / "eventos.csv", run_id)
    resumen = pq.resumir_fases(eventos, tiempos, args.guarda_s, cfg.ventana_s)
    ruta = escribir_resultados(resumen, run_id, args, log_ruta, args.salida, args.docs)
    print(pd.DataFrame(resumen).to_string(index=False))
    print(f"Resumen en {ruta}")
    return 0 if resumen["cumple"].all() else 1


if __name__ == "__main__":
    sys.exit(main())
