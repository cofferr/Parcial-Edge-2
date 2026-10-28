"""Parte 3 (3.1 a 3.3): modelo de energía, ahorro de 8 h y latencia frente a 1 ms."""

import importlib.util
import math
import sys

import pandas as pd
import pytest

from edge_parcial.analysis import energia as en
from edge_parcial.config import RAIZ, RUTA_EJEMPLO

P = en.ParamsEnergia(50e-9, 10e-12, 0.0013e-12, "cita de prueba", 10.0)


def test_d0_y_regimen():
    assert en.d0(P) == pytest.approx(math.sqrt(10e-12 / 0.0013e-12))
    assert en.d0(P) == pytest.approx(87.7058, abs=1e-3)
    reg, razon = en.regimen(P, 10.0)
    assert reg == "espacio_libre" and "d = 10 m < d0" in razon
    assert en.regimen(P, 100.0)[0] == "multitrayecto"
    assert en.regimen(P, en.d0(P))[0] == "multitrayecto"  # d >= d0


def test_e_tx_en_cada_regimen_y_continuidad_en_d0():
    k = 1000
    assert en.e_tx(P, k, 10.0) == pytest.approx(50e-9 * k + 10e-12 * k * 10**2)
    assert en.e_tx(P, k, 100.0) == pytest.approx(50e-9 * k + 0.0013e-12 * k * 100**4)
    c = en.d0(P)
    asc = 50e-9 * k + 10e-12 * k * c**2
    assert en.e_tx(P, k, c) == pytest.approx(
        asc, rel=1e-12
    )  # el modelo es continuo en d0


def test_e_tx_es_lineal_en_k():
    assert en.e_tx(P, 2000, 30.0) == pytest.approx(2 * en.e_tx(P, 1000, 30.0))


def test_tarea_3_1_media_minimo_maximo():
    t = en.tarea_3_1(P, {"media": 26_700.4, "minimo": 24_248.0, "maximo": 32_416.0})
    assert list(t["k_tipo"]) == ["media", "minimo", "maximo"]
    assert (t["regimen"] == "espacio_libre").all()
    fila = t.iloc[0]
    assert fila["E_Tx_J"] == pytest.approx(
        fila["E_electronica_J"] + fila["E_amplificador_J"]
    )
    assert fila["E_Tx_J"] == pytest.approx(en.e_tx(P, 26_700.4, 10.0), rel=1e-12)
    e = t.set_index("k_tipo")["E_Tx_J"]
    assert e["minimo"] < e["media"] < e["maximo"]


def test_tarea_3_2_ahorro_en_julios_y_porcentaje():
    fracc = pd.DataFrame(
        {"p": ["5 %"], "p_valor": [0.05], "f_frames": [0.1], "f_bytes": [0.2]}
    )
    t = en.tarea_3_2(P, 8_000.0, 5.0, fracc)
    n = 5.0 * 8 * 3600
    e1 = en.e_tx(P, 8_000.0, 10.0)
    f = t[t["criterio_f"] == "f_frames"].iloc[0]
    assert f["fotogramas_totales"] == pytest.approx(n)
    assert f["E_todos_J"] == pytest.approx(n * e1)
    assert f["E_filtrado_J"] == pytest.approx(0.1 * n * e1)
    assert f["ahorro_J"] == pytest.approx(0.9 * n * e1) and f[
        "ahorro_pct"
    ] == pytest.approx(90.0)
    b = t[t["criterio_f"] == "f_bytes"].iloc[0]
    assert b["ahorro_pct"] == pytest.approx(80.0)


def test_tarea_3_3_razon_y_diferencia(tmp_path):
    ruta = tmp_path / "reto1.csv"
    pd.DataFrame(
        {
            "modo": ["aislada", "aislada", "concurrente"],
            "fuente": ["droidcam", "droidcam (régimen)", "droidcam"],
            "definicion_L": ["e2e", "régimen", "x"],
            "media_ms": [482.6, 16.7, 1.0], "p50_ms": [475.0, 13.5, 1.0], "p95_ms": [549.9, 28.0, 1.0],
        }
    ).to_csv(ruta, index=False)  # fmt: skip
    t = en.tarea_3_3(ruta)
    frio = t[(t["caso"] == "e2e en frío") & (t["estadistico"] == "media")].iloc[0]
    assert frio["razon"] == pytest.approx(482.6) and frio[
        "diferencia_ms"
    ] == pytest.approx(481.6)
    est = t[(t["caso"] == "régimen estable") & (t["estadistico"] == "p95")].iloc[0]
    assert est["razon"] == pytest.approx(28.0) and est[
        "diferencia_ms"
    ] == pytest.approx(27.0)
    assert len(t) == 6  # 2 casos x (media, p50, p95); el modo concurrente no entra


def test_cargar_params_exige_distancia_y_la_cita(tmp_path):
    base = RUTA_EJEMPLO.read_text(encoding="utf-8")
    cfg = tmp_path / "c.toml"
    cfg.write_text(base, encoding="utf-8")
    with pytest.raises(en.ErrorEnergia, match="distancia_esp32_ap_m"):
        en.cargar_params(cfg)
    cfg.write_text(
        base + "\n[energia.x]\n", encoding="utf-8"
    )  # sección distinta: no engaña
    cfg.write_text(base.replace("# distancia_esp32_ap_m = 0.0", "distancia_esp32_ap_m = 12.5"), encoding="utf-8")  # fmt: skip
    p = en.cargar_params(cfg)
    assert (
        p.distancia_m == 12.5 and p.e_elec == 50e-9 and p.e_mp == pytest.approx(1.3e-15)
    )
    assert "Heinzelman" in p.cita
    sin_cita = base.replace("# distancia_esp32_ap_m = 0.0", "distancia_esp32_ap_m = 1").replace('cita = "', 'cita_x = "')  # fmt: skip
    cfg.write_text(sin_cita, encoding="utf-8")
    with pytest.raises(en.ErrorEnergia, match="cita"):
        en.cargar_params(cfg)


def tablas_sinteticas(tmp_path):
    t = tmp_path / "tablas"
    t.mkdir()
    pd.DataFrame(
        {"fuente": ["esp32"], "tipo": ["carga JPEG"], "media": [3337.55], "minimo": [3031.0], "maximo": [4052.0], "estado": ["ok"]}
    ).to_csv(t / "t1_2_tamano_aislada.csv", index=False)  # fmt: skip
    pd.DataFrame({"fuente": ["esp32"], "fps_medio": [5.2], "estado": ["ok"]}).to_csv(t / "t1_3_fps_aislada.csv", index=False)  # fmt: skip
    pd.DataFrame(
        {"modo": ["aislada"] * 2, "fuente": ["droidcam", "droidcam (régimen)"], "definicion_L": ["a", "b"], "media_ms": [480.0, 16.0], "p50_ms": [470.0, 13.0], "p95_ms": [550.0, 28.0]}
    ).to_csv(t / "reto1_latencia.csv", index=False)  # fmt: skip
    ahorro = tmp_path / "ahorro.csv"
    pd.DataFrame(
        {"fuente": ["esp32", "local"], "p": ["real", "real"], "p_valor": [0.5, 0.5], "f_frames": [0.16, 0.2], "f_bytes": [0.15, 0.2]}
    ).to_csv(ahorro, index=False)  # fmt: skip
    return t, ahorro


def cargar_script():
    espec = importlib.util.spec_from_file_location(
        "t3", RAIZ / "scripts" / "t3_energia.py"
    )
    mod = importlib.util.module_from_spec(espec)
    sys.modules["t3"] = mod
    espec.loader.exec_module(mod)
    return mod


def test_script_se_niega_sin_distancia_y_corre_con_ella(tmp_path, capsys):
    mod = cargar_script()
    t, ahorro = tablas_sinteticas(tmp_path)
    cfg = tmp_path / "c.toml"
    cfg.write_text(RUTA_EJEMPLO.read_text(encoding="utf-8"), encoding="utf-8")
    args = ["--config", str(cfg), "--tablas", str(t), "--ahorro", str(ahorro), "--salida", str(tmp_path / "out")]  # fmt: skip
    assert mod.main(args) == 2
    assert "distancia_esp32_ap_m" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()  # no escribe nada
    cfg.write_text(cfg.read_text().replace("# distancia_esp32_ap_m = 0.0", "distancia_esp32_ap_m = 5.0"), encoding="utf-8")  # fmt: skip
    assert mod.main(args) == 0
    for n in ("t3_1_energia_fotograma", "t3_2_ahorro_8h", "t3_3_latencia_vs_1ms"):
        assert (tmp_path / "out" / f"{n}.csv").is_file() and (tmp_path / "out" / f"{n}.tex").is_file()  # fmt: skip
    r = pd.read_csv(tmp_path / "out" / "t3_1_regimen.csv")
    assert r["regimen"].iloc[0] == "espacio_libre" and "d0" in r["razonamiento"].iloc[0]
