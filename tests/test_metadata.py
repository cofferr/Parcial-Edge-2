"""Pruebas de metadatos de corrida."""

import json
import threading
from dataclasses import replace
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from edge_parcial import metadata
from edge_parcial.config import RUTA_EJEMPLO, cargar_config

SALIDA_WIFI = """\
Wi-Fi:
      Interfaces:
        en0:
          Status: Connected
          Current Network Information:
            <redacted>:
              PHY Mode: 802.11n
              Channel: 1 (2GHz, 20MHz)
              Country Code: CO
              Network Type: Infrastructure
              Security: WPA2 Personal
              Signal / Noise: -25 dBm / -88 dBm
              Transmit Rate: 144
              MCS Index: 15
          Other Local Wi-Fi Networks:
            <redacted>:
              PHY Mode: 802.11b/g/n
              Channel: 3 (2GHz, 20MHz)
"""


class Servidor:
    """Servidor HTTP falso que responde a /status con un cuerpo configurable."""

    def __init__(self, cuerpo: bytes, codigo: int = 200):
        self.cuerpo = cuerpo
        self.codigo = codigo
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(outer.codigo)
                self.send_header("Content-Length", str(len(outer.cuerpo)))
                self.end_headers()
                self.wfile.write(outer.cuerpo)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.puerto = self.httpd.server_address[1]
        self.hilo = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.hilo.start()
        return self

    def __exit__(self, *args):
        self.httpd.shutdown()
        self.httpd.server_close()


def cfg_con(puerto: int):
    cfg = cargar_config(RUTA_EJEMPLO)
    esp = replace(cfg.esp32, ip="127.0.0.1", puerto=puerto)
    return replace(cfg, esp32=esp)


def test_parsear_wifi_real():
    w = metadata.parsear_wifi(SALIDA_WIFI)
    assert w["tasa_transmision_mbps"] == 144.0
    assert w["mcs"] == 15.0
    assert w["modo_phy"] == "802.11n"
    assert w["canal"].startswith("1 ")
    assert w["senal_ruido_dbm"] == "-25 dBm / -88 dBm"


def test_parsear_wifi_sin_red():
    w = metadata.parsear_wifi(
        "Wi-Fi:\n  Interfaces:\n    en0:\n      Status: Inactive\n"
    )
    assert all(v is None for v in w.values())


def test_parsear_wifi_ignora_otras_redes():
    texto = SALIDA_WIFI.replace("Transmit Rate: 144\n", "")
    texto += "              Transmit Rate: 999\n"
    assert metadata.parsear_wifi(texto)["tasa_transmision_mbps"] is None


def test_status_con_fw():
    cuerpo = json.dumps({"fw": "1.2.0", "rssi": -55}).encode()
    with Servidor(cuerpo) as s:
        r = metadata.consultar_status_esp32("127.0.0.1", s.puerto)
    assert r["ok"] and r["fw"] == "1.2.0" and r["rssi_dbm"] == -55


def test_status_sin_fw():
    with Servidor(b'{"rssi_dbm": -60}') as s:
        r = metadata.consultar_status_esp32("127.0.0.1", s.puerto)
    assert not r["ok"] and "fw" in r["error"]


def test_status_caido():
    with Servidor(b"{}") as s:
        puerto = s.puerto
    r = metadata.consultar_status_esp32("127.0.0.1", puerto, timeout=0.5)
    assert not r["ok"] and r["error"]


def test_status_http_error():
    with Servidor(b"x", codigo=500) as s:
        r = metadata.consultar_status_esp32("127.0.0.1", s.puerto)
    assert not r["ok"] and "500" in r["error"]


def test_fw_cambiado_invalida_serie(monkeypatch):
    monkeypatch.setattr(metadata, "leer_wifi_mac", dict)
    with Servidor(b'{"fw": "A"}') as s:
        cfg = cfg_con(s.puerto)
        meta = metadata.recolectar_metadata(cfg, "r1", cpu_duracion_s=0.1)
        assert meta["valida"]
        s.cuerpo = b'{"fw": "B"}'
        meta = metadata.cerrar_metadata(meta, cfg)
    assert not meta["valida"]
    assert "fw cambió" in meta["motivos_invalida"][0]


def test_fw_estable_serie_valida(monkeypatch):
    monkeypatch.setattr(metadata, "leer_wifi_mac", dict)
    with Servidor(b'{"fw": "A"}') as s:
        cfg = cfg_con(s.puerto)
        meta = metadata.recolectar_metadata(cfg, "r1", cpu_duracion_s=0.1)
        meta = metadata.cerrar_metadata(meta, cfg)
    assert meta["valida"]
    assert meta["esp32_status_fin"]["fw"] == "A"


def test_escribir_y_releer(tmp_path, monkeypatch):
    monkeypatch.setattr(metadata, "leer_wifi_mac", lambda: {"mcs": 15.0})
    with Servidor(b'{"fw": "A"}') as s:
        meta = metadata.recolectar_metadata(
            cfg_con(s.puerto),
            "20260101-000000-todas",
            resoluciones={"local": [1920, 1080]},
            cpu_duracion_s=0.1,
        )
    ruta = metadata.escribir_metadata(meta, tmp_path)
    assert ruta == tmp_path / "20260101-000000-todas" / "metadata.json"
    leido = json.loads(ruta.read_text())
    assert leido["resoluciones"]["local"] == [1920, 1080]
    assert datetime.fromisoformat(leido["fecha"]).tzinfo is not None
    assert leido["versiones"]["paquetes"]["psutil"]
    assert set(leido["commit"]) == {"hash", "sucio"}


def test_muestrear_cpu_numero_de_muestras():
    cpu = metadata.muestrear_cpu(duracion_s=0.3, intervalo_s=0.1)
    assert len(cpu["muestras_pct"]) == 3
    assert 0 <= cpu["media_pct"] <= cpu["max_pct"] <= 100


def test_crear_run_id():
    rid = metadata.crear_run_id("todas", datetime(2026, 10, 26, 20, 30, 5))
    assert rid == "20261026-203005-todas"


def test_commit_actual_fuera_de_repo(tmp_path):
    c = metadata.commit_actual(tmp_path)
    assert c == {"hash": None, "sucio": None}


@pytest.mark.skipif(
    metadata.commit_actual()["hash"] is None, reason="el repo aún no tiene commits"
)
def test_commit_actual_en_repo():
    assert len(metadata.commit_actual()["hash"]) == 40
