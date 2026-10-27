"""Tarea 1.4 (tprop) con ping y servidores falsos; sin hardware."""

import importlib.util
import json
import shutil
import sys
import threading

import pytest
from escenario import ServidorFalso, config_hacia, manejador_droidcam, manejador_esp32

from edge_parcial import metadata, tprop
from edge_parcial.analysis import tprop as atp
from edge_parcial.config import RAIZ, RUTA_EJEMPLO, cargar_config

PING_REAL = """\
PING 127.0.0.1 (127.0.0.1): 56 data bytes
64 bytes from 127.0.0.1: icmp_seq=0 ttl=64 time=0.137 ms
64 bytes from 127.0.0.1: icmp_seq=1 ttl=64 time=0.205 ms
Request timeout for icmp_seq 2
64 bytes from 127.0.0.1: icmp_seq=3 ttl=64 time=12.500 ms
64 bytes from 127.0.0.1: icmp_seq=3 ttl=64 time=13.000 ms (DUP!)

--- 127.0.0.1 ping statistics ---
5 packets transmitted, 3 packets received, 40.0% packet loss
"""


@pytest.fixture(autouse=True)
def sin_wifi(monkeypatch):
    monkeypatch.setattr(metadata, "leer_wifi_mac", dict)


def test_parsear_ping_real_con_perdidos_y_duplicados():
    r = tprop.parsear_ping(PING_REAL, 5)
    assert r == [
        137_000,
        205_000,
        None,
        12_500_000,
        None,
    ]  # DUP ignorado; 4.º perdido sin línea


def test_comando_de_ping_usa_intervalo_y_espera():
    visto = {}

    def ejecutor(cmd, timeout):
        visto["cmd"], visto["timeout"] = cmd, timeout
        return 0, ""

    tprop.ejecutar_ping("1.2.3.4", 100, 0.2, 1000, ejecutor)
    assert visto["cmd"] == ["ping", "-c", "100", "-i", "0.2", "-W", "1000", "1.2.3.4"]
    assert visto["timeout"] > 100 * 0.2


@pytest.mark.skipif(shutil.which("ping") is None, reason="sin ping")
def test_ping_real_a_localhost():
    try:
        rtts, salida = tprop.ejecutar_ping("127.0.0.1", 3, 0.2)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"ping no disponible en este entorno: {e}")
    if not any(rtts):
        pytest.skip("ping sin respuesta en este entorno")
    assert all(r is None or r > 0 for r in rtts) and "ping statistics" in salida


def test_rtt_tcp_contra_servidor_y_puerto_cerrado():
    with ServidorFalso(lambda *a: None) as s:
        ok = tprop.rtt_tcp("127.0.0.1", s.puerto, 5, pausa_s=0)
        puerto = s.puerto
    assert all(isinstance(r, int) and r > 0 and e is None for r, e in ok)
    mal = tprop.rtt_tcp("127.0.0.1", puerto, 2, pausa_s=0, timeout_s=0.5)
    assert all(r is None and "ConnectionRefused" in e for r, e in mal)


def test_tprop_fisico_dividido_distancia_velocidad():
    assert tprop.tprop_fisico_s(1.0, 299_792_458) == pytest.approx(3.3356e-9, rel=1e-4)
    assert tprop.tprop_fisico_s(0.0, 299_792_458) == 0


def hacer_ejecutor(rtts_ms, perdidos=(), estado=None):
    """Ping falso: RTT medio por host (ms) con jitter determinista."""

    def ejecutor(cmd, timeout):
        n, host = int(cmd[2]), cmd[-1]
        if estado is not None:
            estado.setdefault("llamadas", []).append((host, estado["activos"]()))
        base = rtts_ms[host]
        lineas = []
        for i in range(n):
            if i in perdidos:
                lineas.append(f"Request timeout for icmp_seq {i}")
            else:
                lineas.append(
                    f"64 bytes from {host}: icmp_seq={i} ttl=64 time={base + (i % 5) * 0.1:.3f} ms"
                )
        return 0, "\n".join(lineas)

    return ejecutor


class Montaje:
    """ESP32 y DroidCam falsos con contador de streams activos."""

    def __init__(self, tmp_path):
        self.activos_n = 0
        self.lock = threading.Lock()
        esp, dc = manejador_esp32(), manejador_droidcam()

        def contar(h):
            def m(conn, req, n):
                es_stream = not req.startswith("GET /status")
                if es_stream:
                    with self.lock:
                        self.activos_n += 1
                try:
                    h(conn, req, n)
                finally:
                    if es_stream:
                        with self.lock:
                            self.activos_n -= 1

            return m

        self.s_esp = ServidorFalso(contar(esp))
        self.s_dc = ServidorFalso(contar(dc))
        self.tmp = tmp_path

    def __enter__(self):
        self.s_esp.__enter__()
        self.s_dc.__enter__()
        # Ambas fuentes de red comparten 127.0.0.1: el ejecutor distingue por nombre de host.
        self.ruta = config_hacia(self.tmp, self.s_esp.puerto, self.s_dc.puerto)
        return self

    def __exit__(self, *a):
        self.s_esp.__exit__()
        self.s_dc.__exit__()

    def activos(self):
        with self.lock:
            return self.activos_n


def cfg_hosts(ruta, tmp_path):
    """Config con hosts distintos por fuente solo para el ping falso (no se conecta a ellos)."""
    return cargar_config(ruta)


def test_medicion_completa_en_reposo(tmp_path):
    raw = tmp_path / "raw"
    with Montaje(tmp_path) as m:
        cfg = cargar_config(m.ruta)
        # Mismo host (127.0.0.1) para ambas fuentes: se fija un solo RTT; el gateway es otro.
        ejecutor = hacer_ejecutor({"127.0.0.1": 10.0, cfg.gateway_ip: 2.0})
        meta = tprop.medir_tprop(
            cfg,
            "t1",
            raw,
            n=100,
            intervalo_s=0.2,
            ejecutor=ejecutor,
            log=lambda *a: None,
            cpu_s=0.1,
            pausa_tcp_s=0,
        )
    assert meta["valida"] and meta["contexto"]["tarea"] == "1.4"
    df = atp.cargar_tprop(raw / "t1")
    assert str(df["rtt_ns"].dtype) == "Int64"
    for fuente in ("gateway", "esp32", "droidcam"):
        assert len(df[(df["source"] == fuente) & (df["metodo"] == "icmp")]) == 100
    for fuente in ("esp32", "droidcam"):
        assert len(df[(df["source"] == fuente) & (df["metodo"] == "tcp")]) == 100
    assert (raw / "t1" / "ping_esp32_icmp.txt").exists()  # salida cruda conservada
    res = atp.resumen_tprop(df, cfg).set_index("fuente")
    # RTT = 10,0 + (i%5)*0,1 -> media 10,2 ms; tprop = RTT/2 = 5,1 ms
    assert res.loc["esp32", "rtt_icmp_ms_media"] == pytest.approx(10.2)
    assert res.loc["esp32", "tprop_icmp_ms_media"] == pytest.approx(5.1)
    assert res.loc["esp32", "tprop_icmp_ms_p50"] == pytest.approx(10.2 / 2)
    assert (
        res.loc["esp32", "muestras_icmp_suficientes"]
        and res.loc["esp32", "muestras_tcp_suficientes"]
    )
    assert res.loc["gateway", "rtt_icmp_ms_media"] == pytest.approx(2.2)
    assert res.loc["esp32", "tprop_fisico_ns"] == pytest.approx(
        3.3356, rel=1e-3
    )  # d = 1 m
    assert res.loc["esp32", "razon_medido_fisico"] > 1e5  # el tprop medido >> d/v
    assert res.loc["local", "tprop_icmp_ms_media"] == 0.0
    assert res.loc["esp32", "rtt_carga_ms_n"] == 0


def test_perdidos_reducen_las_muestras_y_se_marca_la_insuficiencia(tmp_path):
    raw = tmp_path / "raw"
    with Montaje(tmp_path) as m:
        cfg = cargar_config(m.ruta)
        ej = hacer_ejecutor(
            {"127.0.0.1": 5.0, cfg.gateway_ip: 1.0}, perdidos=set(range(0, 100, 20))
        )
        tprop.medir_tprop(
            cfg,
            "t1",
            raw,
            n=100,
            ejecutor=ej,
            log=lambda *a: None,
            cpu_s=0.1,
            pausa_tcp_s=0,
        )
    res = atp.resumen_tprop(atp.cargar_tprop(raw / "t1"), cfg).set_index("fuente")
    assert (
        res.loc["esp32", "rtt_icmp_ms_n"] == 95
        and res.loc["esp32", "perdidos_icmp"] == 5
    )
    assert not res.loc["esp32", "muestras_icmp_suficientes"]  # < 100 válidas


def test_rtt_bajo_carga_va_aparte_y_no_altera_tprop(tmp_path):
    raw = tmp_path / "raw"
    estado = {}
    with Montaje(tmp_path) as m:
        cfg = cargar_config(m.ruta)
        estado["activos"] = m.activos
        # Bajo carga el RTT es 10x mayor: debe quedar fuera de tprop.
        base = {"127.0.0.1": 4.0, cfg.gateway_ip: 1.0}

        def ejecutor(cmd, timeout):
            host = cmd[-1]
            factor = 10.0 if (host == "127.0.0.1" and m.activos() > 0) else 1.0
            estado.setdefault("llamadas", []).append((host, m.activos()))
            return hacer_ejecutor({h: v * factor for h, v in base.items()})(
                cmd, timeout
            )

        meta = tprop.medir_tprop(
            cfg,
            "t1",
            raw,
            n=100,
            ejecutor=ejecutor,
            carga=True,
            log=lambda *a: None,
            cpu_s=0.1,
            pausa_tcp_s=0,
        )
    assert meta["valida"], meta["motivos_invalida"]
    df = atp.cargar_tprop(raw / "t1")
    assert set(df["condicion"]) == {"reposo", "carga"}
    # El ping bajo carga se ejecutó con el stream transmitiendo; el de reposo no.
    en_carga = [a for h, a in estado["llamadas"] if h == "127.0.0.1" and a > 0]
    assert len(en_carga) == 2  # una vez por fuente de red
    res = atp.resumen_tprop(df, cfg).set_index("fuente")
    assert res.loc["esp32", "rtt_icmp_ms_media"] == pytest.approx(4.2)  # sin contaminar
    assert res.loc["esp32", "tprop_icmp_ms_media"] == pytest.approx(2.1)
    assert res.loc["esp32", "rtt_carga_ms_media"] == pytest.approx(40.2)  # aparte
    assert not any(
        "carga" in c for c in res.columns if c.startswith("tprop_")
    )  # fuera de la fórmula


def test_esp32_inalcanzable_invalida_solo_esa_fuente(tmp_path):
    raw = tmp_path / "raw"
    with ServidorFalso(manejador_droidcam()) as dc:
        ruta = config_hacia(tmp_path, 1, dc.puerto)  # puerto 1: nadie escucha
        cfg = cargar_config(ruta)
        ej = hacer_ejecutor({"127.0.0.1": 3.0, cfg.gateway_ip: 1.0})
        meta = tprop.medir_tprop(
            cfg,
            "t1",
            raw,
            fuentes=("esp32", "droidcam"),
            n=3,
            ejecutor=ej,
            log=lambda *a: None,
            cpu_s=0.1,
            pausa_tcp_s=0,
        )
    assert not meta["valida"]
    assert not meta["validez_por_fuente"]["esp32"]["valida"]
    assert meta["validez_por_fuente"]["droidcam"]["valida"]


def cargar_script():
    espec = importlib.util.spec_from_file_location(
        "t1_4", RAIZ / "scripts" / "t1_4_tprop.py"
    )
    mod = importlib.util.module_from_spec(espec)
    sys.modules["t1_4"] = mod
    espec.loader.exec_module(mod)
    return mod


def test_script_t1_4(tmp_path, capsys):
    with Montaje(tmp_path) as m:
        cfg = cargar_config(m.ruta)
        ej = hacer_ejecutor({"127.0.0.1": 6.0, cfg.gateway_ip: 2.0})
        rc = cargar_script().main(
            [
                "--config",
                str(m.ruta),
                "--salida",
                str(tmp_path / "raw"),
                "--n",
                "100",
                "--cpu-s",
                "0.1",
                "--pausa-tcp-s",
                "0",
            ],
            ejecutor=ej,
        )
    out = capsys.readouterr().out
    assert rc == 0 and "tprop = RTT/2" in out and "d/v físico" in out
    assert "local: sin enlace de red, tprop = 0" in out
    meta = json.loads(next((tmp_path / "raw").glob("*/metadata.json")).read_text())
    assert (
        meta["contexto"]["tarea"] == "1.4" and meta["v_propagacion_m_s"] == 299_792_458
    )
    assert cargar_script().main(["--fuentes", "x"]) == 2
    assert cargar_script().main(["--config", str(tmp_path / "no.toml")]) == 2


def test_config_de_ejemplo_declara_distancias_menores_a_1m_o_1m():
    cfg = cargar_config(RUTA_EJEMPLO)
    assert cfg.esp32.distancia_m <= 1.0 and cfg.droidcam.distancia_m <= 1.0
