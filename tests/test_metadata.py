"""Pruebas de metadatos de corrida."""

import json
import threading
import time
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

    def __init__(self, cuerpo: bytes, codigo: int = 200, fallos_previos: int = 0):
        self.cuerpo = cuerpo
        self.codigo = codigo
        self.fallos_previos = fallos_previos
        self.peticiones = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.peticiones += 1
                if outer.peticiones <= outer.fallos_previos:
                    self.send_response(503)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
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


def test_status_con_fw_y_rssi():
    cuerpo = json.dumps({"fw": "1.2.0", "rssi": -55}).encode()
    with Servidor(cuerpo) as s:
        r = metadata.consultar_status_esp32("127.0.0.1", s.puerto)
    assert r["ok"] and r["fw"] == "1.2.0" and r["rssi_dbm"] == -55
    assert r["intentos"] == 1


def test_status_sin_fw():
    with Servidor(b'{"rssi": -60}') as s:
        r = metadata.consultar_status_esp32("127.0.0.1", s.puerto)
    assert not r["ok"] and "fw" in r["error"]


def test_status_sin_rssi_es_invalido():
    with Servidor(b'{"fw": "A"}') as s:
        r = metadata.consultar_status_esp32("127.0.0.1", s.puerto)
    assert not r["ok"] and "rssi" in r["error"]


def test_status_no_acepta_claves_alternativas_de_rssi():
    with Servidor(b'{"fw": "A", "rssi_dbm": -60, "X-Rssi-Dbm": -60}') as s:
        r = metadata.consultar_status_esp32("127.0.0.1", s.puerto)
    assert not r["ok"] and r["rssi_dbm"] is None


def test_status_caido_guarda_error_literal_y_un_reintento():
    with Servidor(b"{}") as s:
        puerto = s.puerto
    r = metadata.consultar_status_esp32("127.0.0.1", puerto, timeout=0.5)
    assert not r["ok"]
    assert "ConnectionRefusedError" in r["error"]
    assert r["intentos"] == 2


def test_status_reintento_recupera():
    with Servidor(b'{"fw": "A", "rssi": -50}', fallos_previos=1) as s:
        r = metadata.consultar_status_esp32("127.0.0.1", s.puerto)
        assert s.peticiones == 2
    assert r["ok"] and r["intentos"] == 2


def test_status_nunca_mas_de_un_reintento():
    with Servidor(b"x", codigo=500) as s:
        r = metadata.consultar_status_esp32("127.0.0.1", s.puerto)
        assert s.peticiones == 2
    assert not r["ok"] and "500" in r["error"]


def test_timeout_corto_en_status():
    import socket

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)  # acepta conexiones pero nunca responde
    t0 = time.monotonic()
    r = metadata.consultar_status_esp32(
        "127.0.0.1", srv.getsockname()[1], timeout=0.3, reintentos=1
    )
    srv.close()
    assert not r["ok"] and "timeout" in r["error"].lower()
    assert time.monotonic() - t0 < 3


def test_timeout_por_defecto_es_corto():
    assert metadata.TIMEOUT_STATUS_S <= 3.0
    assert metadata.REINTENTOS_STATUS == 1


def test_solo_droidcam_no_consulta_status(monkeypatch):
    monkeypatch.setattr(metadata, "leer_wifi_mac", dict)
    with Servidor(b"x") as s:
        puerto = s.puerto
    # ESP32 inalcanzable, pero no se usa en la corrida.
    meta = metadata.recolectar_metadata(
        cfg_con(puerto), "r1", fuentes=("droidcam",), cpu_duracion_s=0.1
    )
    meta = metadata.cerrar_metadata(meta, cfg_con(puerto))
    assert meta["valida"] and meta["motivos_invalida"] == []
    assert meta["esp32_status_inicio"] is None
    assert "esp32_status_fin" not in meta


def test_esp32_caida_invalida_solo_a_la_esp32(monkeypatch):
    monkeypatch.setattr(metadata, "leer_wifi_mac", dict)
    with Servidor(b"x") as s:
        puerto = s.puerto
    meta = metadata.recolectar_metadata(
        cfg_con(puerto), "r1", fuentes=("esp32", "droidcam"), cpu_duracion_s=0.1
    )
    assert not meta["valida"]
    assert not meta["validez_por_fuente"]["esp32"]["valida"]
    assert meta["validez_por_fuente"]["droidcam"]["valida"]
    assert meta["motivos_invalida"][0].startswith("esp32:")


def test_fuente_desconocida():
    with pytest.raises(ValueError):
        metadata.recolectar_metadata(
            cargar_config(RUTA_EJEMPLO), "r1", fuentes=("otra",), cpu_duracion_s=0.1
        )


def test_wifi_se_captura_al_inicio_y_al_cierre(monkeypatch):
    tasas = iter([144.0, 130.0])
    monkeypatch.setattr(
        metadata, "leer_wifi_mac", lambda: {"tasa_transmision_mbps": next(tasas)}
    )
    meta = metadata.recolectar_metadata(
        cargar_config(RUTA_EJEMPLO), "r1", fuentes=("droidcam",), cpu_duracion_s=0.1
    )
    meta = metadata.cerrar_metadata(meta, cargar_config(RUTA_EJEMPLO))
    assert meta["wifi_mac_inicio"]["tasa_transmision_mbps"] == 144.0
    assert meta["wifi_mac_fin"]["tasa_transmision_mbps"] == 130.0


def test_fw_cambiado_invalida_serie(monkeypatch):
    monkeypatch.setattr(metadata, "leer_wifi_mac", dict)
    with Servidor(b'{"fw": "A", "rssi": -50}') as s:
        cfg = cfg_con(s.puerto)
        meta = metadata.recolectar_metadata(cfg, "r1", cpu_duracion_s=0.1)
        assert meta["valida"]
        s.cuerpo = b'{"fw": "B", "rssi": -50}'
        meta = metadata.cerrar_metadata(meta, cfg)
    assert not meta["valida"]
    assert "fw cambió" in meta["motivos_invalida"][0]


def test_fw_estable_serie_valida(monkeypatch):
    monkeypatch.setattr(metadata, "leer_wifi_mac", dict)
    with Servidor(b'{"fw": "A", "rssi": -50}') as s:
        cfg = cfg_con(s.puerto)
        meta = metadata.recolectar_metadata(cfg, "r1", cpu_duracion_s=0.1)
        meta = metadata.cerrar_metadata(meta, cfg)
    assert meta["valida"]
    assert meta["esp32_status_fin"]["fw"] == "A"


def test_escribir_y_releer(tmp_path, monkeypatch):
    monkeypatch.setattr(metadata, "leer_wifi_mac", lambda: {"mcs": 15.0})
    with Servidor(b'{"fw": "A", "rssi": -50}') as s:
        meta = metadata.recolectar_metadata(
            cfg_con(s.puerto),
            "20260101-000000-todas",
            resoluciones={"local": [1920, 1080]},
            cpu_duracion_s=0.1,
        )
        meta = metadata.cerrar_metadata(meta, cfg_con(s.puerto))
    ruta = metadata.escribir_metadata(meta, tmp_path)
    assert ruta == tmp_path / "20260101-000000-todas" / "metadata.json"
    leido = json.loads(ruta.read_text())
    assert "wifi_mac_inicio" in leido and "wifi_mac_fin" in leido
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
