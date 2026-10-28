"""Tarea 1.5: L teórico vs e2e medido, brecha de velocidad y ancho de banda (datos sintéticos)."""

import csv
import importlib.util
import math
import sys

import pytest
from datos_sinteticos import (
    escribir_corrida,
    escribir_tprop,
    filas_e2e,
    filas_local,
    filas_red,
)

from edge_parcial.analysis import tarea_1_5 as t15
from edge_parcial.analysis.carga import cargar_corridas
from edge_parcial.analysis.tprop import elegir_tprop
from edge_parcial.config import RAIZ, RUTA_EJEMPLO, cargar_config

WIFI = {
    "wifi_mac_inicio": {"tasa_transmision_mbps": 144.0},
    "wifi_mac_fin": {"tasa_transmision_mbps": 130.0},
}


@pytest.fixture
def cfg():
    return cargar_config(RUTA_EJEMPLO)


def montar(raw):
    escribir_corrida(
        raw, "e2e-esp", filas_e2e("e2e-esp", "esp32", "/capture", 40, capture_us=100000, flush_us=30, jpeg_us=2000),
        tarea="1.5", fuentes=["esp32"], corrida=1, extra_meta={"contexto": {"tarea": "1.5", "modo": "aislada", "corrida": 1, "fuente": "esp32", "metodo_e2e": "capture"}},
    )  # fmt: skip
    escribir_corrida(
        raw, "e2e-dc", filas_e2e("e2e-dc", "droidcam", "/video", 40, payload=40000, resp_ms=20.0, decode_ms=6.0),
        tarea="1.5", fuentes=["droidcam"], corrida=1, extra_meta={**WIFI, "contexto": {"tarea": "1.5", "modo": "aislada", "corrida": 1, "fuente": "droidcam", "metodo_e2e": "stream"}},
    )  # fmt: skip
    escribir_corrida(
        raw, "e2e-loc", filas_local("e2e-loc", 40), tarea="1.5", fuentes=["local"], corrida=1,
        extra_meta={"contexto": {"tarea": "1.5", "modo": "aislada", "corrida": 1, "fuente": "local", "metodo_e2e": "read"}},
    )  # fmt: skip
    escribir_tprop(raw, "tp1", {"gateway": 2.0, "esp32": 10.0, "droidcam": 6.0})


def test_L_teorico_con_valores_conocidos(tmp_path, cfg):
    montar(tmp_path)
    corridas = cargar_corridas(tmp_path)
    tp, run = elegir_tprop(tmp_path, cfg)
    assert run == "tp1"
    lat = t15.tabla_latencia(corridas, cfg, tp, run).set_index("fuente")
    e = lat.loc["esp32"]
    ttx = (
        3000 * 8 / 72_200_000 * 1000
    )  # 0,3324 ms con la velocidad nominal de la config
    assert e["ttx_teorico_ms"] == pytest.approx(ttx)
    assert e["tprop_ms"] == pytest.approx(5.0)  # RTT/2
    assert e["tproc_dispositivo_ms"] == pytest.approx(102.03)  # flush + capture + jpeg
    assert e["tproc_host_ms"] == pytest.approx(2.0)  # solo decodificación, sin la cola
    assert e["espera_cola_ms"] == pytest.approx(0.5)
    assert e["L_teorico_ms"] == pytest.approx(ttx + 5.0 + 102.03 + 2.0)
    assert e["L_medido_ms"] == pytest.approx(108 + 4 + 0.5 + 2)  # t_ready - t_request
    assert e["discrepancia_ms"] == pytest.approx(114.5 - e["L_teorico_ms"])
    assert e["discrepancia_pct"] == pytest.approx(
        100 * e["discrepancia_ms"] / e["L_teorico_ms"]
    )
    assert e["L_teorico_p50_ms"] == pytest.approx(e["L_teorico_ms"])  # datos constantes


def test_droidcam_usa_la_tasa_wifi_de_la_metadata_de_la_corrida(tmp_path, cfg):
    montar(tmp_path)
    corridas = cargar_corridas(tmp_path)
    tp, run = elegir_tprop(tmp_path, cfg)
    d = t15.tabla_latencia(corridas, cfg, tp, run).set_index("fuente").loc["droidcam"]
    assert d["v_nominal_mbps"] == pytest.approx(137.0)  # media de 144 y 130
    assert d["ttx_teorico_ms"] == pytest.approx(40000 * 8 / 137e6 * 1000)
    assert d["tproc_dispositivo_ms"] == 0.0  # DroidCam no expone cabeceras
    assert d["tprop_ms"] == pytest.approx(3.0)
    assert d["L_teorico_ms"] == pytest.approx(d["ttx_teorico_ms"] + 3.0 + 6.0)


def test_sin_tasa_wifi_el_L_teorico_queda_vacio_y_no_se_inventa(tmp_path, cfg):
    montar(tmp_path)
    corridas = cargar_corridas(tmp_path)
    for c in corridas:
        c.meta.pop("wifi_mac_inicio", None)
        c.meta.pop("wifi_mac_fin", None)
    tp, run = elegir_tprop(tmp_path, cfg)
    d = t15.tabla_latencia(corridas, cfg, tp, run).set_index("fuente").loc["droidcam"]
    assert math.isnan(d["L_teorico_ms"]) and "incompleto" in d["nota"]
    assert d["L_medido_ms"] == pytest.approx(20 + 4 + 0.5 + 6)  # lo medido sigue ahí


def test_local_solo_e2e_medido(tmp_path, cfg):
    montar(tmp_path)
    tp, run = elegir_tprop(tmp_path, cfg)
    loc = (
        t15.tabla_latencia(cargar_corridas(tmp_path), cfg, tp, run)
        .set_index("fuente")
        .loc["local"]
    )
    assert loc["L_medido_ms"] == pytest.approx(33.0) and math.isnan(loc["L_teorico_ms"])
    assert "sin modelo de red" in loc["nota"]


def test_stream_etiqueta_sin_espera_de_sensor(tmp_path, cfg):
    filas = filas_e2e("r", "esp32", "/stream", 30, capture_us=1000, jpeg_us=2000)
    escribir_corrida(tmp_path, "r", filas, tarea="1.5", fuentes=["esp32"], extra_meta={"contexto": {"tarea": "1.5", "modo": "aislada", "corrida": 1}})  # fmt: skip
    r = t15.latencia_fuente(cargar_corridas(tmp_path)[0], "esp32", cfg, None)
    assert r["tproc_dispositivo_ms"] == pytest.approx(3.0)  # capture + jpeg, sin flush
    assert "sin espera de sensor" in r["tproc_dispositivo_etiqueta"]
    assert math.isnan(r["tprop_ms"])  # sin tprop no se inventa


def test_corrida_e2e_invalida_se_excluye(tmp_path, cfg):
    filas = filas_e2e("r", "esp32", "/capture", 30, capture_us=1, flush_us=1, jpeg_us=1)
    validez = {"esp32": {"valida": False, "motivos": ["fw cambió durante la serie"]}}
    escribir_corrida(tmp_path, "r", filas, tarea="1.5", fuentes=["esp32"], validez=validez, extra_meta={"contexto": {"tarea": "1.5", "modo": "aislada", "corrida": 1}})  # fmt: skip
    r = t15.latencia_fuente(cargar_corridas(tmp_path)[0], "esp32", cfg, None)
    assert not r["utilizable"] and "EXCLUIDA" in r["estado"] and "L_teorico_ms" not in r


def test_brecha_y_ancho_de_banda(tmp_path, cfg):
    raw = tmp_path / "raw"
    escribir_corrida(raw, "a-esp", filas_red("a-esp", "esp32", "/stream", 60, payload=2000, ttx_ms=2.0, periodo_ms=125.0), corrida=1)  # fmt: skip
    escribir_corrida(raw, "a-loc", filas_local("a-loc", 60, lectura_ms=40.0), fuentes=["local"], corrida=1)  # fmt: skip
    corridas = cargar_corridas(raw)
    from edge_parcial.analysis import tarea_1_2_1_3 as t12

    res = t12.resumenes(corridas)
    br = t15.tabla_brecha(res, corridas, cfg).iloc[0]
    assert br["v_nominal_mbps"] == pytest.approx(72.2)
    assert br["v_efectiva_mbps"] == pytest.approx(8.0, rel=0.02)  # ~2002 B / 2 ms
    assert br["razon_efectiva_nominal"] == pytest.approx(br["v_efectiva_mbps"] / 72.2)
    ab = t15.tabla_ancho_banda(res).set_index(["fuente", "tipo"])
    # esp32: ~2002 B * 8 * 8 FPS = ~0,128 Mbps ; local JPEG ~90003 B * 8 * 25 FPS = ~18 Mbps
    assert ab.loc[("esp32", "carga JPEG"), "ancho_banda_mbps"] == pytest.approx(
        0.128, rel=0.01
    )
    assert ab.loc[
        ("local", "JPEG q50 (referencia)"), "ancho_banda_mbps"
    ] == pytest.approx(18.0, rel=0.01)
    total = ab.loc[("TOTAL", "JPEG (sin bruto)"), "ancho_banda_mbps"]
    assert total == pytest.approx(ab.loc[("esp32", "carga JPEG"), "ancho_banda_mbps"] + ab.loc[("local", "JPEG q50 (referencia)"), "ancho_banda_mbps"])  # fmt: skip
    assert ab.loc[("local", "bruto"), "ancho_banda_mbps"] > 1000  # 6,2 MB * 8 * 25 FPS


def test_generar_todo_produce_tablas_con_valores_sin_redondear(tmp_path, cfg):
    raw, sal = tmp_path / "raw", tmp_path / "tablas"
    montar(raw)
    escribir_corrida(
        raw, "a-esp", filas_red("a-esp", "esp32", "/stream", 40), corrida=1
    )
    escritas = t15.generar_todo(raw, sal, cfg)
    assert {"t1_4_tprop", "t1_5_latencia", "t1_5_brecha_velocidad", "t1_5_ancho_banda", "t1_3_ttx_aislada"} <= set(escritas)  # fmt: skip
    for base in escritas.values():
        assert base.with_suffix(".csv").exists() and base.with_suffix(".tex").exists()
    with open(sal / "t1_5_latencia.csv") as f:
        filas = {r["fuente"]: r for r in csv.DictReader(f)}
    valor = filas["esp32"]["L_teorico_ms"]
    assert len(valor.split(".")[1]) > 6  # CSV con precisión completa
    tex = (sal / "t1_5_latencia.tex").read_text()
    assert (
        valor not in tex and f"{float(valor):.3f}" in tex
    )  # el redondeo solo en LaTeX
    assert (sal / "t1_5_latencia_completa.csv").exists()
    assert "tabular" in (sal / "t1_4_tprop.tex").read_text()


def test_script_analisis(tmp_path, capsys):
    raw = tmp_path / "raw"
    montar(raw)
    espec = importlib.util.spec_from_file_location(
        "a15", RAIZ / "scripts" / "t1_5_analisis.py"
    )
    mod = importlib.util.module_from_spec(espec)
    sys.modules["a15"] = mod
    espec.loader.exec_module(mod)
    args = [
        "--raw",
        str(raw),
        "--salida",
        str(tmp_path / "s"),
        "--config",
        str(RUTA_EJEMPLO),
    ]
    assert mod.main(args) == 0 and "t1_5_latencia" in capsys.readouterr().out
    vacio = ["--raw", str(tmp_path / "nada"), "--salida", str(tmp_path / "s2"), "--config", str(RUTA_EJEMPLO)]  # fmt: skip
    assert mod.main(vacio) == 1


def test_desglose_esp32_y_reto1(tmp_path, cfg):
    from edge_parcial.analysis import desglose_e2e as d

    montar(tmp_path)
    corridas = cargar_corridas(tmp_path)
    tp, _ = elegir_tprop(tmp_path, cfg)
    with pytest.raises(ValueError, match="RTT por connect TCP"):
        d.desglose_esp32(d.ultima_utilizable(corridas, "1.5", "esp32"), cfg, tp)
    tp.loc[tp["fuente"] == "esp32", ["rtt_tcp_ms_media", "rtt_tcp_ms_p95", "rtt_tcp_ms_n"]] = [8.0, 12.0, 100]  # fmt: skip
    c = d.ultima_utilizable(corridas, "1.5", "esp32")
    t = d.desglose_esp32(c, cfg, tp).set_index(["tramo", "componente"])
    # El tramo de decodificación cierra exacto: cola + decodificación = total, residuo 0.
    tr = t.loc["t_last→t_ready"]
    assert tr.loc["residuo", "media_ms"] == 0
    assert tr.loc["espera en cola", "media_ms"] + tr.loc["decodificación", "media_ms"] == pytest.approx(tr.loc["total medido", "media_ms"])  # fmt: skip
    # Residuo de arranque = total − RTT TCP medio − tproc_dispositivo (medias).
    a = t.loc["t_request→t_first"]
    assert a.loc["residuo", "media_ms"] == pytest.approx(
        a.loc["total medido", "media_ms"]
        - a.loc["red (1 RTT TCP: 0,5 ida + 0,5 vuelta)", "media_ms"]
        - a.loc["tproc_dispositivo (flush+capture+jpeg)", "media_ms"]
    )

    ve = d.velocidad_efectiva_esp32(c, cfg).set_index("cobertura")
    assert ve.loc["todas", "n"] == 40 >= ve.loc["solo n_recv>1", "n"]
    assert ve.loc["todas", "velocidad_efectiva_mbps"] >= ve.loc["solo n_recv>1", "velocidad_efectiva_mbps"]  # fmt: skip

    reto = d.tabla_reto1(corridas, lmax_ms=1e9)
    assert reto[reto["definicion_L"] == "e2e: t_ready − t_request"]["cumple"].all()
    reto0 = d.tabla_reto1(corridas, lmax_ms=0.0)
    ok = reto0.dropna(subset=["p95_ms"])
    assert not ok["cumple"].any()
    assert (ok["brecha_p95_media_ms"] == ok["p95_ms"] - ok["media_ms"]).all()
