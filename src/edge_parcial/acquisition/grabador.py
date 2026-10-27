"""Grabador guiado de la Tarea 1.6: tres fuentes simultáneas con segmentos en el tiempo.

Guion por defecto: 60 s de calibración con la escena estática y 5 ciclos de 15 s
estático / 15 s con actividad. El hilo principal dibuja las indicaciones (macOS) y
registra los límites de cada segmento (`segmentos.csv`, mismo reloj perf_counter_ns que
las marcas de los fotogramas). Cada JPEG transmitido por la fuente se guarda tal cual en
`<dir>/<run_id>/<fuente>/<seq:06d>.jpg` (para el local, el JPEG q=50 de referencia).
`data/recordings` contiene rostros y va fuera de git.
"""

import csv
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter_ns

import numpy as np

from edge_parcial import metadata
from edge_parcial.acquisition.codificador_jpeg import CodificadorJPEG
from edge_parcial.acquisition.lector_local import LectorLocal, crear_camara
from edge_parcial.acquisition.lector_red import (
    LectorStream,
    spec_droidcam,
    spec_esp32_stream,
)
from edge_parcial.acquisition.pantalla import TECLA_Q, Pantalla
from edge_parcial.acquisition.registro import RegistroCSV
from edge_parcial.acquisition.tres_fuentes import _con_texto
from edge_parcial.config import Config

COLUMNAS_SEGMENTOS = ["run_id", "idx", "tipo", "ciclo", "t_ini_ns", "t_fin_ns"]
TIPOS = ("calibracion", "estatico", "actividad")
INDICACION = {
    "calibracion": "CALIBRACION: escena ESTATICA, no te muevas",
    "estatico": "ESTATICO: quieto, sin mover nada",
    "actividad": "ACTIVIDAD: muevete frente a las camaras",
}


@dataclass(frozen=True)
class Segmento:
    tipo: str
    ciclo: int
    duracion_s: float


def guion_estandar(
    calibracion_s: float = 60.0,
    ciclos: int = 5,
    estatico_s: float = 15.0,
    actividad_s: float = 15.0,
) -> list[Segmento]:
    g = [Segmento("calibracion", 0, calibracion_s)]
    for k in range(1, ciclos + 1):
        g.append(Segmento("estatico", k, estatico_s))
        g.append(Segmento("actividad", k, actividad_s))
    return g


class GuardadorJPEG(threading.Thread):
    """Consumidor de las fuentes de red: guarda el JPEG válido; no decodifica."""

    def __init__(self, cola: queue.Queue, sink_fila, directorio: Path, nombre: str):
        super().__init__(name=nombre, daemon=True)
        self.cola, self.sink_fila, self.directorio = cola, sink_fila, Path(directorio)
        self.directorio.mkdir(parents=True, exist_ok=True)
        self.guardados = 0

    def cerrar(self, espera: float = 10.0) -> None:
        self.cola.put(None)
        self.join(espera)

    def run(self) -> None:
        while (item := self.cola.get()) is not None:
            fila = item.fila
            if item.decodificar:
                guardar_jpeg(self.directorio, fila["seq"], item.payload)
                self.guardados += 1
            else:
                fila["error"] = fila["error"] or "JPEG inválido: no se guardó"
            self.sink_fila(fila)


def guardar_jpeg(directorio: Path, seq: int, datos: bytes) -> None:
    (Path(directorio) / f"{seq:06d}.jpg").write_bytes(datos)


def _panel(segmento: Segmento, restante_s: float, n: int, conteos: dict) -> np.ndarray:
    lineas = [
        INDICACION[segmento.tipo],
        f"ciclo {segmento.ciclo}   quedan {restante_s:4.1f} s   (q = abortar)",
        f"segmentos {n}",
    ] + [f"{f}: {c} fotogramas" for f, c in conteos.items()]
    return _con_texto(None, lineas)


def ejecutar_grabacion(
    cfg: Config,
    run_id: str,
    fuentes: tuple[str, ...],
    guion: list[Segmento],
    dir_rec: Path,
    pantalla: Pantalla,
    *,
    camara_factory=crear_camara,
    efectos_confirmados: bool = False,
    cpu_s: float = 2.0,
) -> dict:
    """Graba todo el guion. Devuelve la metadata (con `abortada` si se pulsó q)."""
    params = cfg.lector
    meta = metadata.recolectar_metadata(
        cfg,
        run_id,
        fuentes=fuentes,
        efectos_confirmados=efectos_confirmados,
        cpu_duracion_s=cpu_s,
        contexto={
            "tarea": "1.6",
            "fuentes": list(fuentes),
            "guion": [vars(s) for s in guion],
        },
    )
    fw = (meta["esp32_status_inicio"] or {}).get("fw")
    carpeta = Path(dir_rec) / run_id
    registro = RegistroCSV(carpeta)
    lectores, consumidores, segmentos = [], [], []
    camara = props = None
    abortada = False
    try:
        for f in fuentes:
            cola = queue.Queue(maxsize=params.cola_max)
            destino = carpeta / f
            destino.mkdir(parents=True, exist_ok=True)
            if f == "local":
                camara = camara_factory(cfg)
                props = camara.abrir()
                consumidores.append(
                    CodificadorJPEG(
                        cola,
                        registro.fila,
                        cfg.local.jpeg_calidad,
                        "codificador-local",
                        sink_jpeg=lambda fila, datos, d=destino: guardar_jpeg(
                            d, fila["seq"], datos
                        ),
                    )
                )
                lectores.append(
                    LectorLocal(
                        camara, props, params, cfg.local.ancho, cfg.local.alto, run_id,
                        "grabacion", cola, registro.fila, registro.evento, None,
                    )
                )  # fmt: skip
            else:
                spec = spec_esp32_stream(cfg) if f == "esp32" else spec_droidcam(cfg)
                consumidores.append(
                    GuardadorJPEG(cola, registro.fila, destino, f"guardador-{f}")
                )
                lectores.append(
                    LectorStream(
                        spec, params, run_id, "grabacion", fw if f == "esp32" else None,
                        cola, registro.fila, registro.evento, None,
                    )
                )  # fmt: skip
        for c in consumidores:
            c.start()
        for lector in lectores:
            lector.start()
        for i, seg in enumerate(guion):
            t_ini = perf_counter_ns()
            fin = time.monotonic() + seg.duracion_s
            while (restante := fin - time.monotonic()) > 0:
                conteos = {
                    fu: la._seq for fu, la in zip(fuentes, lectores, strict=True)
                }
                pantalla.mostrar("Grabador 1.6", _panel(seg, restante, i + 1, conteos))
                if pantalla.tecla(30) in (TECLA_Q, ord("Q")):
                    abortada = True
                    break
            segmentos.append((i, seg, t_ini, perf_counter_ns()))
            if abortada:
                break
    finally:
        for lector in lectores:
            lector.detener()
        for lector in lectores:
            lector.join(10)
        for c in consumidores:
            c.cerrar()
        registro.cerrar()
        if camara is not None:
            camara.cerrar()
        pantalla.cerrar()
    with open(carpeta / "segmentos.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNAS_SEGMENTOS)
        for i, seg, t_ini, t_fin in segmentos:
            w.writerow([run_id, i, seg.tipo, seg.ciclo, t_ini, t_fin])
    for f, lector in zip(fuentes, lectores, strict=True):
        resumen = lector.resumen.a_dict()
        if f == "local":
            metadata.registrar_camara_local(meta, props, resumen)
        metadata.registrar_resumen_fuente(meta, f, resumen)
    metadata.cerrar_metadata(meta, cfg)
    meta["abortada"] = abortada
    if abortada:
        meta["valida"] = False
        meta["motivos_invalida"] = [
            *meta.get("motivos_invalida", []),
            "grabación abortada",
        ]
    metadata.escribir_metadata(meta, dir_rec)
    return meta
