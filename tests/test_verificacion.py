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


def _csv(tmp_path, filas):
    from edge_parcial.acquisition.modelo import fila_vacia
    from edge_parcial.acquisition.registro import RegistroCSV

    with RegistroCSV(tmp_path) as reg:
        for i, (endpoint, warmup, conexion) in enumerate(filas):
            f = fila_vacia()
            f.update(
                run_id="r", source="s", endpoint=endpoint, seq=i, warmup=warmup,
                conexion=conexion, t_first_ns=i, t_last_ns=i, n_recv=1, descartado=0,
            )  # fmt: skip
            reg.fila(f)
    return tmp_path / "frames.csv"


def test_resumen_csv_marca_reconexion_entre_medidas(tmp_path):
    ruta = _csv(tmp_path, [("/stream", 1, 0), ("/stream", 0, 0), ("/stream", 0, 1)])
    assert resumir_frames(ruta)["con_reconexiones"] is True


def test_resumen_csv_reconexion_en_warmup_no_marca(tmp_path):
    ruta = _csv(tmp_path, [("/stream", 1, 0), ("/stream", 0, 1), ("/stream", 0, 1)])
    assert resumir_frames(ruta)["con_reconexiones"] is False


def test_resumen_csv_capture_no_marca(tmp_path):
    ruta = _csv(tmp_path, [("/capture", 0, 0), ("/capture", 0, 1), ("/capture", 0, 2)])
    assert resumir_frames(ruta)["con_reconexiones"] is False


# -- cámara local ------------------------------------------------------------


def _config_pequena(tmp_path, ancho=192, alto=108):
    texto = RUTA_EJEMPLO.read_text().replace("ancho = 1920", f"ancho = {ancho}")
    texto = texto.replace("alto = 1080", f"alto = {alto}")
    ruta = tmp_path / "config.toml"
    ruta.write_text(texto)
    return ruta


def _sin_hardware(monkeypatch):
    from edge_parcial import metadata

    monkeypatch.setattr(metadata, "leer_wifi_mac", dict)
    monkeypatch.setattr(metadata, "muestrear_cpu", lambda *a, **k: {"media_pct": 0.0})


def _correr_local(tmp_path, monkeypatch, camara, extra=(), ancho=192, alto=108):
    import json

    _sin_hardware(monkeypatch)
    rc = cargar_script().main(
        [
            "--fuente", "local", "--segundos", "1.5",
            "--config", str(_config_pequena(tmp_path, ancho, alto)),
            "--salida", str(tmp_path / "raw"), *extra,
        ],
        camara=camara,
    )  # fmt: skip
    carpeta = next((tmp_path / "raw").iterdir())
    return rc, json.loads((carpeta / "metadata.json").read_text()), carpeta


def test_script_local_confirmado_es_valido_y_guarda_la_metadata(
    tmp_path, monkeypatch, capsys
):
    from edge_parcial.acquisition.lector_local import CamaraSimulada

    cam = CamaraSimulada(192, 108, intervalo_s=0.02, fps_reportado=30.0)
    rc, meta, carpeta = _correr_local(
        tmp_path, monkeypatch, cam, extra=["--confirmo-efectos-desactivados"]
    )
    assert rc == 0 and meta["valida"] and meta["motivos_invalida"] == []
    c = meta["camara_local"]
    assert c["efectos_desactivados_confirmados"] is True
    assert c["resolucion_solicitada"] == [192, 108] and c["resolucion_real"] == [
        192,
        108,
    ]
    assert c["fps_reportado"] == 30.0 and meta["resoluciones"]["local"] == [192, 108]
    assert meta["fuentes_usadas"] == ["local"] and not cam.abierta  # cámara liberada
    res = resumir_frames(carpeta / "frames.csv")
    assert res["filas_warmup"] == 20 and res["filas_medidas"] > 0
    assert res["raw_bytes_medio"] == 192 * 108 * 3
    assert res["jpeg_ref_bytes_medio"] > 0 and res["codificacion_ms_p50"] > 0
    assert 15 < res["lectura_ms_p50"] < 40  # ~ periodo simulado
    assert 25 < res["fps_medio"] < 60
    assert res["resoluciones"] == ["192x108"]
    assert "Corrida válida" in capsys.readouterr().out


def test_script_local_sin_confirmacion_de_efectos_es_invalido(
    tmp_path, monkeypatch, capsys
):
    from edge_parcial.acquisition.lector_local import CamaraSimulada

    rc, meta, _ = _correr_local(
        tmp_path, monkeypatch, CamaraSimulada(192, 108, intervalo_s=0.02)
    )
    assert rc == 0 and not meta["valida"]
    assert meta["camara_local"]["efectos_desactivados_confirmados"] is False
    assert "--confirmo-efectos-desactivados" in meta["motivos_invalida"][0]
    assert "CORRIDA INVÁLIDA" in capsys.readouterr().out


def test_script_local_resolucion_distinta_invalida(tmp_path, monkeypatch):
    from edge_parcial.acquisition.lector_local import CamaraSimulada

    cam = CamaraSimulada(128, 72, intervalo_s=0.02)  # la cámara entrega otra resolución
    _, meta, _ = _correr_local(
        tmp_path, monkeypatch, cam, extra=["--confirmo-efectos-desactivados"]
    )
    assert not meta["valida"]
    assert meta["camara_local"]["resolucion_real"] == [128, 72]
    assert any("128x72" in m and "192x108" in m for m in meta["motivos_invalida"])


def test_script_local_no_fuerza_el_fps():
    import inspect

    from edge_parcial.acquisition import lector_local

    assert "CAP_PROP_FPS" in inspect.getsource(
        lector_local.CamaraCV2.abrir
    )  # solo lo lee
    assert "set(cv2.CAP_PROP_FPS" not in inspect.getsource(lector_local)


def test_script_local_error_si_no_abre_la_camara(tmp_path, monkeypatch, capsys):
    from edge_parcial.acquisition.lector_local import ErrorCamara

    class NoAbre:
        def abrir(self):
            raise ErrorCamara("no abre")

    _sin_hardware(monkeypatch)
    rc = cargar_script().main(
        ["--fuente", "local", "--config", str(_config_pequena(tmp_path)),
         "--salida", str(tmp_path / "raw")],
        camara=NoAbre(),
    )  # fmt: skip
    assert rc == 3 and "no abre" in capsys.readouterr().err
