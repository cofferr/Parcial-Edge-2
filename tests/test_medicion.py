"""Medición Tareas 1.2/1.3 extremo a extremo contra servidores y cámara falsos."""

import importlib.util
import json
import sys

import pytest
from escenario import ServidorFalso, config_hacia, manejador_droidcam, manejador_esp32

from edge_parcial import metadata
from edge_parcial.acquisition.lector_local import CamaraSimulada
from edge_parcial.config import RAIZ


@pytest.fixture(autouse=True)
def sin_hardware(monkeypatch):
    monkeypatch.setattr(
        metadata, "leer_wifi_mac", lambda: {"tasa_transmision_mbps": 144.0}
    )


def cargar_script():
    ruta = RAIZ / "scripts" / "t1_2_1_3_medicion.py"
    espec = importlib.util.spec_from_file_location("t1_2_1_3_medicion", ruta)
    mod = importlib.util.module_from_spec(espec)
    sys.modules["t1_2_1_3_medicion"] = mod
    espec.loader.exec_module(mod)
    return mod


def camara(cfg):
    return CamaraSimulada(cfg.local.ancho, cfg.local.alto, intervalo_s=0.002)


def correr(tmp_path, modo, corridas=1, n=10, extra=(), esp=None, dc=None):
    esp = esp or manejador_esp32()
    dc = dc or manejador_droidcam()
    with ServidorFalso(esp) as s_esp, ServidorFalso(dc) as s_dc:
        ruta = config_hacia(tmp_path, s_esp.puerto, s_dc.puerto)
        rc = cargar_script().main(
            [
                "--modo", modo, "--corridas", str(corridas), "--n", str(n),
                "--config", str(ruta), "--salida", str(tmp_path / "raw"),
                "--pausa-s", "0", "--cpu-s", "0.1", "--confirmo-efectos-desactivados", *extra,
            ],
            camara_factory=camara,
        )  # fmt: skip
    metas = [
        json.loads(p.read_text())
        for p in sorted((tmp_path / "raw").glob("*/metadata.json"))
    ]
    return rc, metas


def filas(tmp_path, meta):
    import csv

    with open(tmp_path / "raw" / meta["run_id"] / "frames.csv", newline="") as f:
        return list(csv.DictReader(f))


def test_modo_concurrente_las_tres_a_la_vez(tmp_path):
    rc, metas = correr(tmp_path, "concurrente", corridas=2, n=10)
    assert rc == 0 and len(metas) == 2
    m = metas[0]
    assert m["valida"], m["motivos_invalida"]
    assert m["contexto"] == {
        "tarea": "1.2_1.3", "modo": "concurrente", "corrida": 1, "fuente": "todas",
        "fuentes": ["local", "esp32", "droidcam"], "n_medidas": 10, "warmup": 20,
    }  # fmt: skip
    f = filas(tmp_path, m)
    for fuente in ("local", "esp32", "droidcam"):
        propias = [r for r in f if r["source"] == fuente]
        assert len(propias) == 30  # 20 de warmup + 10 medidos
        assert sum(r["warmup"] == "1" for r in propias) == 20
    assert {r["condition"] for r in f} == {"concurrente"}
    esp = [r for r in f if r["source"] == "esp32"]
    assert {r["fw"] for r in esp} == {"T1"} and all(
        r["endpoint"] == "/stream" for r in esp
    )
    assert m["esp32_status_inicio"]["fw"] == m["esp32_status_fin"]["fw"] == "T1"
    assert "wifi_mac_inicio" in m and "wifi_mac_fin" in m


def test_modo_aislada_una_fuente_por_unidad(tmp_path):
    rc, metas = correr(tmp_path, "aislada", corridas=1, n=5)
    assert rc == 0 and len(metas) == 3
    assert {m["contexto"]["fuente"] for m in metas} == {"local", "esp32", "droidcam"}
    for m in metas:
        f = filas(tmp_path, m)
        assert {r["source"] for r in f} == {m["contexto"]["fuente"]}
        assert len(f) == 25 and {r["condition"] for r in f} == {"aislada"}
        assert m["valida"], m["motivos_invalida"]
    # Solo la unidad de la ESP32 consulta /status.
    por = {m["contexto"]["fuente"]: m for m in metas}
    assert (
        por["esp32"]["esp32_status_inicio"]
        and por["droidcam"]["esp32_status_inicio"] is None
    )


def test_datos_crudos_sin_redondear(tmp_path):
    _, metas = correr(tmp_path, "aislada", n=3, extra=["--fuentes", "esp32"])
    f = filas(tmp_path, metas[0])
    for r in f:
        for col in ("t_first_ns", "t_last_ns", "t_ready_ns", "t_request_ns"):
            assert r[col].isdigit(), (col, r[col])  # enteros en ns, no floats
        assert (
            int(r["t_request_ns"])
            < int(r["t_first_ns"])
            <= int(r["t_last_ns"])
            <= int(r["t_ready_ns"])
        )


def test_fw_que_cambia_invalida_solo_la_serie_de_la_esp32(tmp_path):
    estado = {"n": 0}
    base = manejador_esp32()

    def esp(conn, req, n):
        if req.startswith("GET /status"):
            estado["n"] += 1
            import json as j

            cuerpo = j.dumps({"fw": f"V{estado['n']}", "rssi": -50}).encode()
            conn.sendall(
                b"HTTP/1.1 200 OK\r\n"
                + f"Content-Length: {len(cuerpo)}\r\n\r\n".encode()
                + cuerpo
            )
            return
        base(conn, req, n)

    _, metas = correr(tmp_path, "aislada", n=3, esp=esp)
    por = {m["contexto"]["fuente"]: m for m in metas}
    assert (
        not por["esp32"]["valida"]
        and "fw cambió" in por["esp32"]["motivos_invalida"][0]
    )
    assert por["droidcam"]["valida"] and por["local"]["valida"]


def test_cabeceras_faltantes_invalidan_la_esp32(tmp_path):
    _, metas = correr(tmp_path, "aislada", n=3, esp=manejador_esp32(sin_cabeceras=True))
    por = {m["contexto"]["fuente"]: m for m in metas}
    assert not por["esp32"]["valida"]
    assert "cabeceras obligatorias ausentes" in por["esp32"]["motivos_invalida"][0]


def test_sin_confirmar_efectos_la_local_es_invalida(tmp_path):
    with (
        ServidorFalso(manejador_esp32()) as e,
        ServidorFalso(manejador_droidcam()) as d,
    ):
        ruta = config_hacia(tmp_path, e.puerto, d.puerto)
        cargar_script().main(
            ["--modo", "aislada", "--corridas", "1", "--n", "3", "--fuentes", "local",
             "--config", str(ruta), "--salida", str(tmp_path / "raw"),
             "--pausa-s", "0", "--cpu-s", "0.1"],
            camara_factory=camara,
        )  # fmt: skip
    m = json.loads(next((tmp_path / "raw").glob("*/metadata.json")).read_text())
    assert not m["valida"] and "efectos" in m["motivos_invalida"][0]


def test_reconexion_dentro_de_los_medidos_se_marca(tmp_path):
    """El servidor corta el stream a mitad: la corrida queda marcada, no promediada."""
    import time

    from servidor_falso import cabecera_http, cabeceras_esp32, enviar, hacer_jpeg, parte

    jp = hacer_jpeg(1, 64, 48)

    def esp(conn, req, n):
        if req.startswith("GET /status"):
            manejador_esp32()(conn, req, n)
            return
        enviar(conn, cabecera_http())
        total = 24 if n == 1 else 1000  # la 1.ª conexión corta tras 24 (4 medidos)
        for i in range(total):
            try:
                enviar(conn, parte(jp, cabeceras=cabeceras_esp32(i)))
            except OSError:
                return
            time.sleep(0.001)
        if n == 1:
            return

    _, metas = correr(tmp_path, "aislada", n=10, extra=["--fuentes", "esp32"], esp=esp)
    m = metas[0]
    assert m["lectores"]["esp32"]["con_reconexiones"] is True
    assert m["lectores"]["esp32"]["reconexiones"] >= 1


def test_argumentos_invalidos(tmp_path, capsys):
    mod = cargar_script()
    assert mod.main(["--modo", "aislada", "--fuentes", "x"]) == 2
    assert mod.main(["--modo", "aislada", "--config", str(tmp_path / "no.toml")]) == 2
