"""Tarea 2.4: latencia por capas con CSV sintéticos de valores conocidos."""

import json

import pandas as pd
import pytest

from edge_parcial.capas import analisis
from edge_parcial.capas.registro import COLUMNAS_FOTOGRAMAS, COLUMNAS_VENTANAS, FUENTES

MS = 1_000_000
S = 1_000_000_000
BASE = 10_000 * S


def fotograma(src, seq, k, t_first_ms, ready_ms, ini_ms, fin_ms, **kw):
    f = dict.fromkeys(COLUMNAS_FOTOGRAMAS)
    f.update(
        source=src, seq=seq, ventana=k, t_request_ns=BASE + (t_first_ms - 1) * MS,
        t_first_ns=None if src == "local" else BASE + t_first_ms * MS,
        t_ready_ns=BASE + ready_ms * MS, t_edge_ini_ns=BASE + ini_ms * MS,
        t_edge_fin_ns=BASE + fin_ms * MS, evaluado=1, fraccion=0.1, luminancia=100.0,
        movimiento=1, cambio_global=0, tapada=0, tardio=0,
    )  # fmt: skip
    f.update(kw)
    return f


def ventana(k, t_decision_ms, votos_ms, alerta=1):
    v = dict.fromkeys(COLUMNAS_VENTANAS)
    v.update(
        ventana=k, t_ini_ns=BASE + k * S, t_decision_ns=BASE + t_decision_ms * MS,
        ts_wall="x", Q=2, n_true=3, alerta=alerta,
    )  # fmt: skip
    for f in FUENTES:
        v[f"voto_{f}"] = 1
        v[f"bandera_{f}"] = "movimiento"
        v[f"fraccion_{f}"] = 0.5
        v[f"n_fotogramas_{f}"] = 5
        v[f"t_voto_ns_{f}"] = BASE + votos_ms[f] * MS
    return v


@pytest.fixture
def corrida(tmp_path):
    """Dos ventanas de arranque descartadas (0, 1) y dos válidas (2, 3)."""
    fotos, vents = [], []
    for seq, k in enumerate(range(4)):
        t0 = k * 1000
        # esp32: device 50 ms, edge 5 ms (cola 1 + cómputo 4); local: device 5, edge 3
        fotos.append(fotograma("esp32", seq, k, t0 + 100, t0 + 150, t0 + 151, t0 + 155, capture_us=40_000, jpeg_us=6_000))  # fmt: skip
        fotos.append(
            fotograma("droidcam", seq, k, t0 + 200, t0 + 220, t0 + 221, t0 + 224)
        )
        fotos.append(fotograma("local", seq, k, t0 + 300, t0 + 305, t0 + 305, t0 + 308))
        # votos emitidos en t0 + 1250; la decisión 2 ms después de la última
        vents.append(ventana(k, t0 + 1253, {"esp32": t0 + 1250, "droidcam": t0 + 1251, "local": t0 + 1252}))  # fmt: skip
    # un fotograma tardío (su ventana ya estaba votada) y uno de la ventana 2 con otra fuente
    fotos.append(fotograma("esp32", 99, 2, 2900, 2960, 2961, 3500, tardio=1))
    pd.DataFrame(fotos, columns=COLUMNAS_FOTOGRAMAS).to_csv(tmp_path / "capas_fotogramas.csv", index=False)  # fmt: skip
    pd.DataFrame(vents, columns=COLUMNAS_VENTANAS).to_csv(tmp_path / "capas_ventanas.csv", index=False)  # fmt: skip
    return tmp_path


def test_terminos_de_cada_capa(corrida):
    fotos, vents = analisis.cargar(corrida)
    df = analisis.calcular_capas(fotos, vents)
    e = df[(df.source == "esp32") & (df.ventana == 2) & (df.tardio == 0)].iloc[0]
    assert e.device_ms == pytest.approx(50.0)  # t_first -> t_ready
    assert e.edge_ms == pytest.approx(5.0) and e.edge_cola_ms == pytest.approx(1.0)
    assert e.edge_computo_ms == pytest.approx(4.0)
    assert e.fog_ms == pytest.approx(3.0)  # decisión t0+1253, voto t0+1250
    assert e.l_ventana_ms == pytest.approx((2000 + 1250) - (2000 + 155))
    assert e.ltotal_ms == pytest.approx(50 + 5 + 3)
    assert e.tproc_dispositivo_ms == pytest.approx(46.0)  # capture + jpeg
    assert e.e2e_ms == pytest.approx(e.ltotal_ms + e.l_ventana_ms)


def test_local_usa_t_request_como_inicio_del_device(corrida):
    fotos, vents = analisis.cargar(corrida)
    df = analisis.calcular_capas(fotos, vents)
    loc = df[(df.source == "local") & (df.ventana == 2)].iloc[0]
    assert loc.device_ms == pytest.approx(
        6.0
    )  # t_request = t_first_equiv - 1 ms; ready - request
    assert pd.isna(loc.tproc_dispositivo_ms)


def test_l_ventana_no_entra_en_lfog_ni_ltotal_y_la_identidad_se_cumple(corrida):
    fotos, vents = analisis.cargar(corrida)
    df = analisis.calcular_capas(fotos, vents)
    assert analisis.identidad_e2e(df) < 1e-9
    v = df[df.valido]
    assert (v.l_ventana_ms > 900).all()  # ~1 s de espera de diseño
    assert (v.fog_ms < 10).all() and (v.ltotal_ms < 100).all()


def test_tardios_y_arranque_se_excluyen(corrida):
    fotos, vents = analisis.cargar(corrida)
    df = analisis.calcular_capas(fotos, vents)
    assert not df[df.tardio == 1].valido.any()
    assert not df[df.ventana < analisis.VENTANAS_ARRANQUE].valido.any()
    assert pd.isna(df[df.tardio == 1].fog_ms).all()
    est = analisis.tabla_estadisticos(df)
    n = est[(est.fuente == "esp32") & (est.metrica == "device_ms")].n.iloc[0]
    assert n == 2  # ventanas 2 y 3; el tardío no cuenta


def test_estadisticos_completos_y_fog_por_ventana(corrida):
    fotos, vents = analisis.cargar(corrida)
    est = analisis.tabla_estadisticos(analisis.calcular_capas(fotos, vents))
    fila = est[(est.fuente == "droidcam") & (est.metrica == "device_ms")].iloc[0]
    assert fila.media == pytest.approx(20.0) and fila.minimo == fila.maximo == fila.p50 == fila.p95  # fmt: skip
    assert list(est.columns) == ["fuente", "metrica", "n", "media", "minimo", "maximo", "desviacion", "p50", "p95"]  # fmt: skip
    assert est[(est.fuente == "local") & (est.metrica == "fog_ms")].n.iloc[0] == 2


def test_capa_que_mas_contribuye_a_la_diferencia(corrida):
    fotos, vents = analisis.cargar(corrida)
    dif, capa = analisis.diferencia_entre_fuentes(analisis.calcular_capas(fotos, vents))
    assert capa == "device"  # esp32 50 ms vs local 6 ms
    assert dif.fuente_alta.iloc[0] == "esp32" and dif.fuente_baja.iloc[0] == "local"
    assert dif.pct_de_la_diferencia.sum() == pytest.approx(
        100.0
    )  # descomposición exacta
    d = dif.set_index("capa").delta_ms
    assert d["device"] == pytest.approx(44.0) and d["edge"] == pytest.approx(2.0)


def test_evento_alerta_incluye_l_ventana(corrida):
    fotos, vents = analisis.cargar(corrida)
    ev = analisis.evento_alerta(analisis.calcular_capas(fotos, vents))
    esp = ev[ev.grupo == "esp32"].iloc[0]
    assert esp.n == 2 and esp.media > 1000  # incluye la espera de la ventana
    assert ev.iloc[-1].grupo == "ventana (peor caso)"


def test_escribir_tablas_csv_latex_y_resumen(corrida, tmp_path):
    salida = tmp_path / "out"
    resumen = analisis.escribir_tablas(corrida, salida)
    assert resumen["capa_que_mas_contribuye"] == "device"
    assert resumen["fotogramas_tardios"] == 1
    for n in ("capas", "evento_alerta", "diferencia"):
        assert (salida / f"t2_4_{n}.csv").is_file() and (
            salida / f"t2_4_{n}.tex"
        ).is_file()
    assert json.loads((salida / "t2_4_resumen.json").read_text())["ventanas"] == 4
    crudo = pd.read_csv(salida / "t2_4_capas.csv")
    assert crudo.media.iloc[0] == pytest.approx(50.0)  # CSV sin redondear


def test_script_t2_4_simulado_de_punta_a_punta(tmp_path):
    import importlib.util
    import sys

    from edge_parcial.config import RAIZ, RUTA_EJEMPLO
    from edge_parcial.edge.detector import ParamsDetector
    from edge_parcial.nucleo import config_p2

    espec = importlib.util.spec_from_file_location(
        "t2_4", RAIZ / "scripts" / "t2_4_capas.py"
    )
    mod = importlib.util.module_from_spec(espec)
    sys.modules["t2_4"] = mod
    espec.loader.exec_module(mod)
    cfg = tmp_path / "config.toml"
    cfg.write_text(RUTA_EJEMPLO.read_text(encoding="utf-8"), encoding="utf-8")
    config_p2.escribir_secciones_detector(
        cfg, {f: ParamsDetector(32.0, 0.01, 0.3) for f in config_p2.FUENTES}
    )
    rc = mod.main(
        ["--simular", "--duracion-s", "6", "--ciclo-s", "2", "--calentamiento-s", "1",
         "--config", str(cfg), "--raw", str(tmp_path / "raw"), "--salida", str(tmp_path / "proc")]
    )  # fmt: skip
    assert rc == 0
    resumen = json.loads((tmp_path / "proc" / "t2_4_resumen.json").read_text())
    assert (
        resumen["capa_que_mas_contribuye"] == "device"
    )  # retardos simulados distintos
    assert resumen["max_desviacion_identidad_e2e_ms"] < 1e-6
    run = next((tmp_path / "raw").iterdir())
    assert (run / "segmentos.csv").is_file() and (run / "eventos.csv").is_file()
    # --analizar re-analiza una corrida existente
    assert mod.main(["--analizar", str(run), "--salida", str(tmp_path / "proc2")]) == 0
    assert (tmp_path / "proc2" / "t2_4_capas.tex").is_file()
