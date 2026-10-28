"""Tarea 2.1: parser de nmap/lsof, AS = N x I y el script con nmap simulado."""

import importlib.util
import json
import sys
from types import SimpleNamespace

import pytest

from edge_parcial.analysis import auditoria as aud
from edge_parcial.config import RAIZ, RUTA_EJEMPLO

XML = """<?xml version="1.0"?>
<nmaprun><host><ports>
<port protocol="tcp" portid="80"><state state="open" reason="syn-ack"/>
<service name="http" product="esp32 httpd" version="1.0" extrainfo="x"/></port>
<port protocol="tcp" portid="81"><state state="open" reason="syn-ack"/><service name="http"/></port>
<port protocol="udp" portid="5353"><state state="open|filtered" reason="no-response"/><service name="mdns"/></port>
</ports></host></nmaprun>"""

LSOF = """COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
ControlCe 512 yo   10u  IPv4 0x1      0t0  TCP *:7000 (LISTEN)
ControlCe 512 yo   11u  IPv6 0x2      0t0  TCP [::1]:7000 (LISTEN)
python    900 yo    5u  IPv4 0x3      0t0  TCP 127.0.0.1:8000 (LISTEN)
rapportd  610 yo    8u  IPv4 0x4      0t0  TCP 172.19.160.104:49152 (LISTEN)
"""


def test_parsear_nmap_xml(tmp_path):
    ruta = tmp_path / "x.xml"
    ruta.write_text(XML)
    filas = aud.parsear_nmap_xml(ruta)
    assert [(f["puerto"], f["protocolo"], f["estado"]) for f in filas] == [
        (80, "tcp", "open"),
        (81, "tcp", "open"),
        (5353, "udp", "open|filtered"),
    ]
    assert filas[0]["servicio"] == "http"
    assert filas[0]["version"] == "esp32 httpd 1.0 x"


def test_parsear_lsof_y_loopback():
    e = aud.parsear_lsof(LSOF)
    assert [(x.direccion, x.puerto, x.es_loopback) for x in e] == [
        ("0.0.0.0", 7000, False),
        ("[::1]", 7000, True),
        ("127.0.0.1", 8000, True),
        ("172.19.160.104", 49152, False),
    ]


def test_interfaces_host_solo_cuenta_no_loopback():
    nmap = [
        {
            "puerto": 7000,
            "protocolo": "tcp",
            "estado": "open",
            "servicio": "afs3",
            "version": "",
            "razon": "",
        }
    ]
    filas = aud.interfaces_host(aud.parsear_lsof(LSOF), nmap)
    tabla = aud.tabla_interfaces({"host": filas})
    cuentan = tabla[tabla["cuenta_en_I"]]["puerto"].tolist()
    assert sorted(cuentan) == [7000, 49152]
    assert 8000 in tabla["puerto"].tolist()  # loopback listado, no cuenta
    assert (
        "confirmado por nmap"
        in filas[[f["puerto"] for f in filas].index(7000)]["observaciones"]
    )


def test_as_n_por_i_sin_redondear():
    tabla = aud.tabla_interfaces(
        {
            "esp32": [
                {"puerto": 80, "protocolo": "tcp", "estado": "open"},
                {"puerto": 81, "protocolo": "tcp", "estado": "open"},
            ],
            "droidcam": [
                {"puerto": 4747, "protocolo": "tcp", "estado": "open"},
                {"puerto": 5353, "protocolo": "udp", "estado": "open|filtered"},
            ],
            "host": [
                {"puerto": p, "protocolo": "tcp", "estado": "open"}
                for p in (1, 2, 3, 4)
            ],
        }
    )
    a = aud.calcular_as(tabla, ["esp32", "droidcam", "local"], "a")
    assert a["I"].tolist() == [
        2.0,
        1.0,
        0.0,
        1.0,
    ]  # open|filtered no cuenta; total = media
    assert a["N"].tolist() == [1, 1, 1, 3]
    assert a["AS"].tolist() == [2.0, 1.0, 0.0, 3.0]
    b = aud.calcular_as(tabla, ["esp32", "droidcam", "local", "host"], "b")
    assert b.iloc[-1]["N"] == 4 and b.iloc[-1]["I"] == 7 / 4 and b.iloc[-1]["AS"] == 7.0


def test_sondear_http_sin_autenticacion(servidor_http):
    ip, puerto = servidor_http
    obs = aud.sondear_http(ip, puerto)
    assert "sin autenticación (GET / → 200 sin credenciales)" in obs
    assert "rutas desconocidas devuelven 200" in obs


@pytest.fixture
def servidor_http():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address
    srv.shutdown()


def _cargar_script():
    espec = importlib.util.spec_from_file_location(
        "t2_1", RAIZ / "scripts" / "t2_1_auditoria.py"
    )
    mod = importlib.util.module_from_spec(espec)
    sys.modules["t2_1"] = mod
    espec.loader.exec_module(mod)
    return mod


def _config_con_ips(tmp_path):
    texto = RUTA_EJEMPLO.read_text(encoding="utf-8")
    ruta = tmp_path / "config.toml"
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def test_script_con_nmap_simulado(tmp_path, monkeypatch):
    mod = _cargar_script()
    monkeypatch.setattr(
        mod.metadata,
        "consultar_status_esp32",
        lambda ip, puerto: {
            "ok": True,
            "fw": "fw-test",
            "error": None,
            "rssi_dbm": -40,
            "intentos": 1,
        },
    )
    llamadas = []

    def ejecutar(cmd, **kw):
        llamadas.append(cmd)
        if cmd[0] == "lsof":
            return SimpleNamespace(returncode=0, stdout=LSOF)
        base = cmd[cmd.index("-oX") + 1]
        from pathlib import Path

        Path(base).write_text(XML)
        Path(base.replace(".xml", ".txt")).write_text("normal")
        return SimpleNamespace(returncode=0)

    raw, salida = tmp_path / "raw", tmp_path / "out"
    rc = mod.main(
        [
            "--fase",
            "tcp",
            "--config",
            str(_config_con_ips(tmp_path)),
            "--raw",
            str(raw),
            "--salida",
            str(salida),
        ],
        ejecutar=ejecutar,
        sondear=lambda ip, p: ["sin autenticación"],
        ips={"esp32": "1.1.1.1", "droidcam": "2.2.2.2", "host": "3.3.3.3"},
    )
    assert rc == 0
    nmaps = [c for c in llamadas if c[0] == "nmap"]
    assert len(nmaps) == 3
    esp = next(c for c in nmaps if c[-1] == "1.1.1.1")
    assert [
        "-p-",
        "-Pn",
        "-sT",
        "--open",
        "-sV",
        "--version-light",
        "--max-retries",
        "1",
    ] == esp[1:9]
    assert "--max-rate" in esp
    assert "--max-rate" not in next(c for c in nmaps if c[-1] == "2.2.2.2")
    meta = json.loads(next(raw.glob("*/auditoria.json")).read_text())
    assert meta["esp32_dejo_de_responder"] is False
    assert [s["momento"] for s in meta["esp32_status"]] == ["antes-tcp", "despues-tcp"]
    assert (salida / "t2_1_as.csv").is_file() and (
        salida / "t2_1_interfaces.tex"
    ).is_file()
    texto = (salida / "t2_1_interfaces.csv").read_text()
    assert "sin autenticación" in texto


def test_script_sin_nmap_indica_brew(monkeypatch, capsys, tmp_path):
    mod = _cargar_script()
    monkeypatch.setattr(mod.shutil, "which", lambda _: None)
    assert mod.main(["--fase", "tcp"]) == 2
    assert "brew install nmap" in capsys.readouterr().err
