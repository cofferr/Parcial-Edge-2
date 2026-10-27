"""Tareas 1.2/1.3: corridas de medición de tamaño y ttx con las tres fuentes.

Modos:
- "aislada": una fuente a la vez (un run_id por fuente y corrida).
- "concurrente": las tres a la vez (un run_id por corrida, `source` distingue las filas).

ESP32-CAM: /stream (ttx y tamaño). Su /capture se mide en la Tarea 1.5 (e2e).
Por fuente: `warmup_fotogramas` de calentamiento (warmup=1, no se promedian) más `n`
fotogramas medidos. Datos crudos en data/raw/<run_id>/{frames,eventos}.csv + metadata.json.
"""

import queue
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from edge_parcial import metadata
from edge_parcial.acquisition.codificador_jpeg import CodificadorJPEG
from edge_parcial.acquisition.decodificador import Decodificador
from edge_parcial.acquisition.lector_local import LectorLocal, crear_camara
from edge_parcial.acquisition.lector_red import (
    LectorAperturaStream,
    LectorCapture,
    LectorStream,
    SpecFuente,
    spec_droidcam,
    spec_esp32_capture,
    spec_esp32_stream,
)
from edge_parcial.acquisition.registro import RegistroCSV
from edge_parcial.config import Config

MODOS = ("aislada", "concurrente")
FUENTES = ("local", "esp32", "droidcam")
TAREA = "1.2_1.3"


def ejecutar_unidad(
    cfg: Config,
    run_id: str,
    fuentes: tuple[str, ...],
    condition: str,
    n: int,
    dir_raw: Path,
    *,
    camara_factory=crear_camara,
    contexto: dict | None = None,
    efectos_confirmados: bool = False,
    timeout_s: float = 1800.0,
    cpu_s: float = 2.0,
    e2e: bool = False,
) -> dict:
    """Una unidad de medición (1 o 3 fuentes simultáneas). Devuelve la metadata.

    Con `e2e=True` (Tarea 1.5) la ESP32 se mide por /capture con conexión nueva por
    muestra y DroidCam abriendo el stream hasta el primer fotograma decodificado (o por
    la URL de imagen fija de la config).
    """
    params = cfg.lector
    n_total = params.warmup_fotogramas + n
    meta = metadata.recolectar_metadata(
        cfg,
        run_id,
        fuentes=fuentes,
        efectos_confirmados=efectos_confirmados,
        cpu_duracion_s=cpu_s,
        contexto=contexto,
    )
    fw = (meta["esp32_status_inicio"] or {}).get("fw")
    registro = RegistroCSV(Path(dir_raw) / run_id)
    lectores, consumidores = [], []
    camara = props = None
    try:
        for f in fuentes:
            cola = queue.Queue(maxsize=params.cola_max)
            if f == "local":
                camara = camara_factory(cfg)
                props = camara.abrir()  # hilo principal (autorización de macOS)
                consumidores.append(
                    CodificadorJPEG(
                        cola, registro.fila, cfg.local.jpeg_calidad, "codificador-local"
                    )
                )
                lectores.append(
                    LectorLocal(
                        camara,
                        props,
                        params,
                        cfg.local.ancho,
                        cfg.local.alto,
                        run_id,
                        condition,
                        cola,
                        registro.fila,
                        registro.evento,
                        n_total,
                    )
                )
            else:
                clase = LectorStream
                if e2e:
                    spec, clase = _spec_e2e(cfg, f)
                else:
                    spec = (
                        spec_esp32_stream(cfg) if f == "esp32" else spec_droidcam(cfg)
                    )
                consumidores.append(
                    Decodificador(cola, registro.fila, f"decodificador-{f}")
                )
                lectores.append(
                    clase(
                        spec,
                        params,
                        run_id,
                        condition,
                        fw if f == "esp32" else None,
                        cola,
                        registro.fila,
                        registro.evento,
                        n_total,
                    )
                )
        for c in consumidores:
            c.start()
        for lector in lectores:
            lector.start()
        fin = time.monotonic() + timeout_s
        for lector in lectores:
            lector.join(max(0.0, fin - time.monotonic()))
    finally:
        for lector in lectores:
            if lector.is_alive():
                lector.resumen.motivos_extra.append(
                    f"no se alcanzaron {n_total} fotogramas en {timeout_s:.0f} s"
                )
            lector.detener()
        for lector in lectores:
            lector.join(10)
        for c in consumidores:
            c.cerrar()
        registro.cerrar()
        if camara is not None:
            camara.cerrar()
    for f, lector in zip(fuentes, lectores, strict=True):
        resumen = lector.resumen.a_dict()
        if f == "local":
            metadata.registrar_camara_local(meta, props, resumen)
        metadata.registrar_resumen_fuente(meta, f, resumen)
    metadata.cerrar_metadata(meta, cfg)  # /status final con el stream cerrado
    metadata.escribir_metadata(meta, dir_raw)
    return meta


def _spec_e2e(cfg: Config, fuente: str):
    """(spec, clase de lector) del e2e de una fuente de red."""
    if fuente == "esp32":
        return spec_esp32_capture(cfg), LectorCapture
    url = cfg.droidcam.url_imagen_fija
    if url:  # imagen fija: petición -> JPEG
        u = urlparse(url)
        spec = SpecFuente(
            "droidcam",
            u.hostname or cfg.droidcam.ip,
            u.port or cfg.droidcam.puerto,
            u.path or "/",
        )
        return spec, LectorCapture
    return spec_droidcam(cfg), LectorAperturaStream


def ejecutar_medicion(
    cfg: Config,
    modo: str,
    corridas: int,
    n: int,
    fuentes: tuple[str, ...],
    dir_raw: Path,
    *,
    pausa_s: float = 2.0,
    log=print,
    **kw,
) -> list[dict]:
    """Ejecuta `corridas` corridas en el modo dado. Devuelve la metadata de cada unidad."""
    if modo not in MODOS:
        raise ValueError(f"Modo desconocido: {modo}")
    ts = datetime.now()
    resultados = []
    for k in range(1, corridas + 1):
        grupos = [(f,) for f in fuentes] if modo == "aislada" else [tuple(fuentes)]
        for grupo in grupos:
            etiqueta = grupo[0] if modo == "aislada" else "todas"
            run_id = f"{ts:%Y%m%d-%H%M%S}-{modo}-c{k}-{etiqueta}"
            contexto = {
                "tarea": TAREA,
                "modo": modo,
                "corrida": k,
                "fuente": etiqueta,
                "fuentes": list(grupo),
                "n_medidas": n,
                "warmup": cfg.lector.warmup_fotogramas,
            }
            log(f"[{modo}] corrida {k}/{corridas}: {', '.join(grupo)} -> {run_id}")
            meta = ejecutar_unidad(
                cfg, run_id, grupo, modo, n, dir_raw, contexto=contexto, **kw
            )
            estado = (
                "válida"
                if meta["valida"]
                else f"INVÁLIDA ({'; '.join(meta['motivos_invalida'])})"
            )
            marca = [
                f
                for f, r in meta.get("lectores", {}).items()
                if r.get("con_reconexiones")
            ]
            if marca:
                estado += f"; CON RECONEXIONES en {', '.join(marca)} (no se promedia)"
            log(f"    -> {estado}")
            resultados.append(meta)
            if pausa_s:
                time.sleep(pausa_s)
    return resultados


METODO_E2E = {
    "esp32": "/capture con conexión nueva por muestra (petición -> fotograma decodificado)",
    "droidcam": "apertura del stream hasta el primer fotograma decodificado",
    "droidcam_imagen_fija": "URL de imagen fija (petición -> fotograma decodificado)",
    "local": "read() con la cámara abierta",
}


def ejecutar_e2e(
    cfg: Config,
    corridas: int,
    n: int,
    fuentes: tuple[str, ...],
    dir_raw: Path,
    *,
    pausa_s: float = 2.0,
    log=print,
    **kw,
) -> list[dict]:
    """Tarea 1.5: latencia extremo a extremo medida, una fuente a la vez."""
    ts = datetime.now()
    resultados = []
    for k in range(1, corridas + 1):
        for f in fuentes:
            run_id = f"{ts:%Y%m%d-%H%M%S}-e2e-c{k}-{f}"
            metodo = METODO_E2E[
                "droidcam_imagen_fija"
                if f == "droidcam" and cfg.droidcam.url_imagen_fija
                else f
            ]
            contexto = {
                "tarea": "1.5", "modo": "aislada", "corrida": k, "fuente": f, "fuentes": [f],
                "n_medidas": n, "warmup": cfg.lector.warmup_fotogramas, "metodo_e2e": metodo,
            }  # fmt: skip
            log(f"[e2e] corrida {k}/{corridas}: {f} ({metodo}) -> {run_id}")
            meta = ejecutar_unidad(
                cfg, run_id, (f,), "e2e", n, dir_raw, contexto=contexto, e2e=True, **kw
            )
            log(
                "    -> "
                + (
                    "válida"
                    if meta["valida"]
                    else "INVÁLIDA: " + "; ".join(meta["motivos_invalida"])
                )
            )
            resultados.append(meta)
            if pausa_s:
                time.sleep(pausa_s)
    return resultados
