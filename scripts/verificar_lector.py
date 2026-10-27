"""Verificación manual del lector MJPEG contra hardware real (fuera de pytest).

Uso (una fuente a la vez: la ESP32-CAM admite un solo cliente):
    uv run python scripts/verificar_lector.py --fuente esp32-stream  --segundos 30
    uv run python scripts/verificar_lector.py --fuente esp32-capture --segundos 30
    uv run python scripts/verificar_lector.py --fuente droidcam      --segundos 30

Antes de la ESP32: cierra cualquier otro cliente de /stream (navegador, curl, otra corrida).

Cámara local (apertura en el hilo principal, lectura en el hilo lector):
    uv run python scripts/verificar_lector.py --fuente local --segundos 30 \\
        --confirmo-efectos-desactivados
Sin --confirmo-efectos-desactivados la corrida local queda valida:false (Center Stage y
los efectos de video no se pueden leer desde OpenCV; se confirman a mano, ver
docs/verificacion_lector.md).
"""

import argparse
import queue
import sys
import time
from pathlib import Path

from edge_parcial import metadata as meta_mod
from edge_parcial.acquisition.codificador_jpeg import CodificadorJPEG
from edge_parcial.acquisition.decodificador import Decodificador
from edge_parcial.acquisition.lector_local import ErrorCamara, LectorLocal, crear_camara
from edge_parcial.acquisition.lector_red import (
    LectorCapture,
    LectorStream,
    spec_droidcam,
    spec_esp32_capture,
    spec_esp32_stream,
)
from edge_parcial.acquisition.registro import RegistroCSV
from edge_parcial.acquisition.verificacion import resumir_frames
from edge_parcial.config import RAIZ, RUTA_CONFIG, ErrorConfig, cargar_config
from edge_parcial.metadata import crear_run_id

FUENTES = {
    "esp32-stream": (spec_esp32_stream, LectorStream),
    "esp32-capture": (spec_esp32_capture, LectorCapture),
    "droidcam": (spec_droidcam, LectorStream),
    "local": (None, LectorLocal),
}


def _fmt(valor, unidad: str = "", dec: int = 2) -> str:
    return "n/d" if valor is None else f"{valor:.{dec}f}{unidad}"


def imprimir(res: dict, resumen: dict, ruta) -> None:
    print(f"\n== Resultado ({ruta}) ==")
    print(
        f"filas: {res['filas_total']} (warmup {res['filas_warmup']}, medidas "
        f"{res['filas_medidas']}, con error {res['filas_con_error']}, "
        f"descartadas por cola {res['descartadas']})"
    )
    print(
        f"FPS medio: {_fmt(res['fps_medio'])}   inter-arribo ms p50/p95/max: "
        f"{_fmt(res['interarribo_ms_p50'])}/{_fmt(res['interarribo_ms_p95'])}/"
        f"{_fmt(res['interarribo_ms_max'])}   huecos > 1 s: {res['huecos_mayores_1s']}"
    )
    print(
        f"payload medio: {_fmt(res['payload_bytes_medio'], ' B', 0)}   "
        f"resoluciones: {', '.join(res['resoluciones']) or 'n/d'}"
    )
    print(
        f"ttx ms p50/p95 (n_recv>1, {res['ttx_filas_validas']} filas): "
        f"{_fmt(res['ttx_ms_p50'], dec=3)}/{_fmt(res['ttx_ms_p95'], dec=3)}"
    )
    print(
        f"filas con n_recv = 1 (ttx=0 solo resolución): {res['n_recv_1']} "
        f"= {_fmt(res['pct_n_recv_1'], ' %', 1)}"
    )
    print(f"respuesta (t_first - t_request) ms p50: {_fmt(res['respuesta_ms_p50'])}")
    print(
        f"host: espera en cola p50 {_fmt(res['espera_cola_ms_p50'], ' ms', 3)}, "
        f"decodificación p50 {_fmt(res['decodificacion_ms_p50'], ' ms', 3)}"
    )
    print(
        f"dispositivo p50: capture {_fmt(res['capture_us_p50'], ' us', 0)}, "
        f"flush {_fmt(res['flush_us_p50'], ' us', 0)}, jpeg {_fmt(res['jpeg_us_p50'], ' us', 0)}, "
        f"rssi {_fmt(res['rssi_dbm_p50'], ' dBm', 0)}"
    )
    print(
        f"reconexiones: {resumen['reconexiones']}   abandonada: {resumen['abandonada']}   "
        f"descartes: {resumen['descartes']}"
    )
    print(
        f"bytes recibidos por conexión: {resumen['bytes_recv_por_conexion']} "
        f"(total {resumen['bytes_recv_total']}) -> contrastar con tcpdump"
    )
    if resumen["cabeceras_faltantes"]:
        print(f"CABECERAS FALTANTES (filas): {resumen['cabeceras_faltantes']}")
    for a in resumen["advertencias"]:
        print(f"ADVERTENCIA: {a}")
    for m in resumen["motivos_invalida"]:
        print(f"CORRIDA INVÁLIDA: {m}")
    if not resumen["motivos_invalida"]:
        print("Corrida válida para esta fuente.")


def _correr_local(args, cfg, camara) -> int:
    run_id = crear_run_id("verif-local")
    destino = args.salida / run_id
    print(
        f"Verificando cámara local (índice {cfg.local.indice_camara}) durante "
        f"{args.segundos:.0f} s -> {destino}"
    )
    if not args.confirmo_efectos_desactivados:
        print(
            "AVISO: sin --confirmo-efectos-desactivados la corrida local quedará valida:false."
        )
    camara = camara or crear_camara(cfg)
    try:
        propiedades = camara.abrir()  # hilo principal (autorización de AVFoundation)
    except ErrorCamara as e:
        print(f"Error de cámara: {e}", file=sys.stderr)
        return 3
    print(f"Cámara abierta: {propiedades}")
    meta = meta_mod.recolectar_metadata(
        cfg,
        run_id,
        fuentes=("local",),
        efectos_confirmados=args.confirmo_efectos_desactivados,
    )
    registro = RegistroCSV(destino)
    cola = queue.Queue(maxsize=cfg.lector.cola_max)
    codificador = CodificadorJPEG(cola, registro.fila, calidad=cfg.local.jpeg_calidad)
    lector = LectorLocal(
        camara, propiedades, cfg.lector, cfg.local.ancho, cfg.local.alto, run_id,
        args.condicion, cola, registro.fila, registro.evento, None,
    )  # fmt: skip
    codificador.start()
    lector.start()
    try:
        fin = time.monotonic() + args.segundos
        while time.monotonic() < fin and lector.is_alive():
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("Interrumpido; cerrando...")
    finally:
        lector.detener()
        lector.join(10)
        codificador.cerrar()
        registro.cerrar()
        camara.cerrar()
    resumen = lector.resumen.a_dict()
    meta_mod.registrar_camara_local(meta, propiedades, resumen)
    meta_mod.cerrar_metadata(meta, cfg)
    ruta_meta = meta_mod.escribir_metadata(meta, args.salida)
    resumen["motivos_invalida"] = meta["validez_por_fuente"]["local"]["motivos"]
    imprimir(resumir_frames(registro.ruta_frames), resumen, registro.ruta_frames)
    print(
        f"Metadata: {ruta_meta}  (resolución real {meta['camara_local']['resolucion_real']}, "
        f"FPS reportado {meta['camara_local']['fps_reportado']})"
    )
    return 0


def main(argv: list[str] | None = None, *, camara=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--fuente", required=True, choices=sorted(FUENTES))
    ap.add_argument("--segundos", type=float, default=30.0)
    ap.add_argument("--config", type=Path, default=RUTA_CONFIG)
    ap.add_argument("--salida", type=Path, default=RAIZ / "data" / "raw")
    ap.add_argument("--condicion", default="aislada")
    ap.add_argument("--host", help="sustituye la IP de la config (pruebas)")
    ap.add_argument(
        "--puerto", type=int, help="sustituye el puerto de la config (pruebas)"
    )
    ap.add_argument(
        "--confirmo-efectos-desactivados",
        action="store_true",
        help="cámara local: confirmo que Center Stage y los efectos de video están "
        "desactivados (se guarda en la metadata; sin esto la corrida local es inválida)",
    )
    args = ap.parse_args(argv)

    try:
        cfg = cargar_config(args.config)
    except ErrorConfig as e:
        print(f"Error de configuración: {e}", file=sys.stderr)
        return 2
    if args.fuente == "local":
        return _correr_local(args, cfg, camara)
    crear_spec, clase = FUENTES[args.fuente]
    spec = crear_spec(cfg)
    if args.host or args.puerto:
        from dataclasses import replace

        spec = replace(
            spec, host=args.host or spec.host, puerto=args.puerto or spec.puerto
        )

    run_id = crear_run_id(f"verif-{args.fuente}")
    destino = args.salida / run_id
    print(
        f"Verificando {args.fuente} ({spec.host}:{spec.puerto}{spec.ruta}) "
        f"durante {args.segundos:.0f} s -> {destino}"
    )
    if args.fuente.startswith("esp32"):
        print("Recuerda: la ESP32-CAM admite UN solo cliente; cierra navegador/curl.")

    registro = RegistroCSV(destino)
    cola = queue.Queue(maxsize=cfg.lector.cola_max)
    decodificador = Decodificador(cola, registro.fila)
    lector = clase(
        spec,
        cfg.lector,
        run_id,
        args.condicion,
        None,
        cola,
        registro.fila,
        registro.evento,
        None,
    )
    decodificador.start()
    lector.start()
    try:
        fin = time.monotonic() + args.segundos
        while time.monotonic() < fin and lector.is_alive():
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("Interrumpido; cerrando...")
    finally:
        lector.detener()
        lector.join(10)
        decodificador.cerrar()
        registro.cerrar()

    imprimir(
        resumir_frames(registro.ruta_frames),
        lector.resumen.a_dict(),
        registro.ruta_frames,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
