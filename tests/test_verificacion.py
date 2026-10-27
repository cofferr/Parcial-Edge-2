"""Pruebas del resumen de verificación y del script completo contra un servidor falso."""

import importlib.util
import sys

from servidor_falso import (
    ServidorFalso,
    cabecera_http,
    cabeceras_esp32,
    enviar,
    hacer_jpeg,
    parte,
)
from test_lector_red import esperar_cliente

from edge_parcial.acquisition.verificacion import resumir_frames
from edge_parcial.config import RAIZ, RUTA_EJEMPLO


def cargar_script():
    ruta = RAIZ / "scripts" / "verificar_lector.py"
    espec = importlib.util.spec_from_file_location("verificar_lector", ruta)
    modulo = importlib.util.module_from_spec(espec)
    sys.modules["verificar_lector"] = modulo
    espec.loader.exec_module(modulo)
    return modulo


def test_script_extremo_a_extremo_stream(tmp_path, capsys):
    jpegs = [hacer_jpeg(i, 128, 96) for i in range(30)]

    def manejador(conn, req, n):
        enviar(conn, cabecera_http())
        for i, j in enumerate(jpegs):
            enviar(conn, parte(j, cabeceras=cabeceras_esp32(i)), trozo=600, pausa=0.001)
        esperar_cliente(conn)

    with ServidorFalso(manejador) as srv:
        rc = cargar_script().main(
            [
                "--fuente", "esp32-stream", "--segundos", "1.5",
                "--config", str(RUTA_EJEMPLO), "--salida", str(tmp_path),
                "--host", "127.0.0.1", "--puerto", str(srv.puerto),
            ]
        )  # fmt: skip
    assert rc == 0
    salida = capsys.readouterr().out
    assert "Corrida válida" in salida and "n_recv = 1" in salida
    carpeta = next(tmp_path.iterdir())
    res = resumir_frames(carpeta / "frames.csv")
    assert res["filas_total"] == 30 and res["filas_warmup"] == 20
    assert res["resoluciones"] == ["128x96"]
    assert res["decodificacion_ms_p50"] is not None
    assert res["capture_us_p50"] == 1024.5  # mediana de las filas sin warmup (20..29)
    assert (carpeta / "eventos.csv").exists()


def test_script_sin_config_devuelve_error(tmp_path, capsys):
    rc = cargar_script().main(
        [
            "--fuente",
            "droidcam",
            "--config",
            str(tmp_path / "no.toml"),
            "--salida",
            str(tmp_path),
        ]
    )
    assert rc == 2 and "config.example.toml" in capsys.readouterr().err


def test_resumir_frames_sintetico(tmp_path):
    from edge_parcial.acquisition.modelo import COLUMNAS_FRAMES, fila_vacia
    from edge_parcial.acquisition.registro import RegistroCSV

    with RegistroCSV(tmp_path) as reg:
        t = 1_000_000_000
        for i in range(25):
            f = fila_vacia()
            f.update(
                run_id="r", source="s", seq=i, warmup=int(i < 20), conexion=0,
                t_request_ns=t, t_first_ns=t + 100_000_000 * i,
                t_last_ns=t + 100_000_000 * i + (0 if i % 2 else 5_000_000),
                n_recv=1 if i % 2 else 3, payload_bytes=1000, descartado=0,
            )  # fmt: skip
            reg.fila(f)
    assert COLUMNAS_FRAMES
    r = resumir_frames(tmp_path / "frames.csv")
    assert r["filas_warmup"] == 20 and r["filas_medidas"] == 5
    assert r["n_recv_1"] == 2 and round(r["pct_n_recv_1"]) == 40
    assert round(r["ttx_ms_p50"]) == 5 and r["ttx_filas_validas"] == 3
    assert round(r["fps_medio"]) == 10 and r["huecos_mayores_1s"] == 0
