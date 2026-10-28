"""Análisis de las Tareas 1.2/1.3 con datos sintéticos de valores conocidos."""

import csv
import math

import pytest
from datos_sinteticos import T0, escribir_corrida, filas_local, filas_red

from edge_parcial.analysis import tarea_1_2_1_3 as t
from edge_parcial.analysis.carga import cargar_corridas
from edge_parcial.analysis.estadisticas import estadisticos
from edge_parcial.analysis.tablas import a_latex, escribir_tabla, formatear


def test_estadisticos_valores_conocidos():
    e = estadisticos([1, 2, 3, 4, 5])
    assert e["n"] == 5 and e["media"] == 3 and e["minimo"] == 1 and e["maximo"] == 5
    assert e["desviacion"] == pytest.approx(math.sqrt(2.5))  # muestral (ddof=1)
    assert e["p50"] == 3 and e["p95"] == pytest.approx(4.8)


def test_estadisticos_vacio_y_un_valor():
    assert estadisticos([])["n"] == 0 and math.isnan(estadisticos([])["media"])
    uno = estadisticos([7])
    assert uno["media"] == 7 and math.isnan(uno["desviacion"])


def test_ttx_excluye_n_recv_1_y_declara_el_porcentaje(tmp_path):
    filas = filas_red("r1", "esp32", "/stream", n=100, ttx_ms=4.0, uno_cada=4)
    escribir_corrida(tmp_path, "r1", filas)
    c = cargar_corridas(tmp_path)[0]
    r = t.resumen_fuente(c, "esp32")
    # i en 0..119, warmup 20: medidas i=20..119; n_recv=1 cuando i%4==0 -> 25 filas.
    assert r["n_medidas"] == 100 and r["n_recv_1"] == 25 and r["pct_n_recv_1"] == 25.0
    assert r["n_ttx"] == 75
    assert (
        r["ttx_ms_minimo"] >= 4.0
    )  # los ttx = 0 no entran en el mínimo ni en la media
    assert 4.0 <= r["ttx_ms_media"] < 4.01


def test_no_hay_redondeo_en_los_datos_y_las_marcas_ns_son_exactas(tmp_path):
    filas = filas_red("r1", "droidcam", "/video", n=30)
    escribir_corrida(tmp_path, "r1", filas, fuentes=["droidcam"])
    c = cargar_corridas(tmp_path)[0]
    assert str(c.frames["t_first_ns"].dtype) == "Int64"
    assert int(c.frames["t_first_ns"].iloc[0]) == T0  # exacto: > 2**53 no se pierde


def test_tamano_y_velocidad_efectiva(tmp_path):
    filas = filas_red("r1", "esp32", "/stream", n=50, payload=2000, ttx_ms=2.0)
    escribir_corrida(tmp_path, "r1", filas)
    r = t.resumen_fuente(cargar_corridas(tmp_path)[0], "esp32")
    assert 2000 <= r["payload_media"] <= 2004 and r["payload_minimo"] == 2000
    # ~2002 B * 8 / 2 ms = ~8 Mbps
    assert 7.9 < r["velocidad_efectiva_mbps"] < 8.1


def test_fps_desde_interarribos(tmp_path):
    filas = filas_red("r1", "esp32", "/stream", n=60, periodo_ms=125.0)
    escribir_corrida(tmp_path, "r1", filas)
    r = t.resumen_fuente(cargar_corridas(tmp_path)[0], "esp32")
    assert r["fps_medio"] == pytest.approx(8.0, rel=1e-3)
    assert r["interarribo_ms_p50"] == pytest.approx(125.0, rel=1e-3)
    assert r["huecos_mayores_1s"] == 0


def test_huecos_largos(tmp_path):
    filas = filas_red("r1", "esp32", "/stream", n=40, periodo_ms=100.0)
    for f in filas[30:]:  # un hueco de 2 s
        for col in ("t_first_ns", "t_last_ns", "t_decode_ini_ns", "t_ready_ns"):
            f[col] += 2_000_000_000
    escribir_corrida(tmp_path, "r1", filas)
    r = t.resumen_fuente(cargar_corridas(tmp_path)[0], "esp32")
    assert r["huecos_mayores_1s"] == 1 and r["interarribo_ms_maximo"] > 2000


def test_local_raw_y_jpeg_y_lectura(tmp_path):
    escribir_corrida(tmp_path, "r1", filas_local("r1", 40))
    r = t.resumen_fuente(cargar_corridas(tmp_path)[0], "local")
    assert r["raw_media"] == 6_220_800 and r["raw_desviacion"] == 0
    assert r["payload_media"] > 90_000
    assert r["lectura_ms_media"] == pytest.approx(33.0)
    assert r["codificacion_ms_media"] == pytest.approx(8.001, abs=1e-3)
    assert r["fps_medio"] == pytest.approx(1000 / 33.0, rel=1e-3)
    assert "ttx_ms_media" not in r  # la cámara local no tiene ttx de red


def test_corrida_con_reconexion_se_excluye_no_se_promedia(tmp_path):
    filas = filas_red(
        "r1", "esp32", "/stream", n=40, conexion_de=lambda i: 0 if i < 30 else 1
    )
    escribir_corrida(tmp_path, "r1", filas)
    r = t.resumen_fuente(cargar_corridas(tmp_path)[0], "esp32")
    assert (
        not r["utilizable"]
        and "reconexiones" in r["estado"]
        and "ttx_ms_media" not in r
    )


def test_reconexion_solo_en_warmup_no_excluye(tmp_path):
    filas = filas_red(
        "r1", "esp32", "/stream", n=40, conexion_de=lambda i: 0 if i < 10 else 1
    )
    escribir_corrida(tmp_path, "r1", filas)
    assert t.resumen_fuente(cargar_corridas(tmp_path)[0], "esp32")["utilizable"]


def test_corrida_invalida_en_metadata_se_excluye(tmp_path):
    filas = filas_red("r1", "esp32", "/stream", n=20)
    validez = {"esp32": {"valida": False, "motivos": ["fw cambió durante la serie"]}}
    escribir_corrida(tmp_path, "r1", filas, validez=validez)
    r = t.resumen_fuente(cargar_corridas(tmp_path)[0], "esp32")
    assert not r["utilizable"] and "fw cambió" in r["estado"]


def test_filas_con_error_o_jpeg_invalido_no_entran(tmp_path):
    filas = filas_red("r1", "esp32", "/stream", n=30)
    filas[25]["error"] = "x"
    filas[26]["jpeg_valid"] = 0
    escribir_corrida(tmp_path, "r1", filas)
    r = t.resumen_fuente(cargar_corridas(tmp_path)[0], "esp32")
    assert r["n_medidas"] == 30 and r["n_validas"] == 28


def test_tablas_oficiales_usan_la_corrida_1_y_las_demas_quedan_en_consistencia(
    tmp_path,
):
    raw, sal = tmp_path / "raw", tmp_path / "tablas"
    for k, ttx in [(1, 4.0), (2, 8.0), (3, 8.0)]:
        rid = f"r{k}"
        escribir_corrida(
            raw, rid, filas_red(rid, "esp32", "/stream", n=30, ttx_ms=ttx), corrida=k
        )
    generar = t.generar_tablas(cargar_corridas(raw), sal)
    assert {
        "t1_2_tamano_aislada",
        "t1_3_ttx_aislada",
        "t1_3_fps_aislada",
        "t1_2_1_3_corridas_aislada",
    } <= set(generar)
    with open(sal / "t1_3_ttx_aislada.csv") as f:
        filas = list(csv.DictReader(f))
    assert (
        len(filas) == 1 and 4.0 <= float(filas[0]["media"]) < 4.01
    )  # solo la corrida 1
    with open(sal / "t1_2_1_3_corridas_aislada.csv") as f:
        assert len(list(csv.DictReader(f))) == 3


def test_csv_sin_redondear_y_latex_redondeado(tmp_path):
    raw, sal = tmp_path / "raw", tmp_path / "tablas"
    escribir_corrida(raw, "r1", filas_red("r1", "esp32", "/stream", n=30, ttx_ms=4.0))
    t.generar_tablas(cargar_corridas(raw), sal)
    with open(sal / "t1_3_ttx_aislada.csv") as f:
        media_csv = next(csv.DictReader(f))["media"]
    assert len(media_csv.split(".")[1]) > 3  # decimales completos en el CSV
    tex = (sal / "t1_3_ttx_aislada.tex").read_text()
    assert "\\begin{tabular}" in tex and "\\toprule" in tex and "esp32" in tex
    assert media_csv not in tex  # el LaTeX solo lleva el valor redondeado (3 decimales)
    assert f"{float(media_csv):.3f}" in tex


def test_corrida_excluida_aparece_en_la_tabla_oficial_marcada(tmp_path):
    raw, sal = tmp_path / "raw", tmp_path / "tablas"
    filas = filas_red(
        "r1", "esp32", "/stream", n=30, conexion_de=lambda i: 0 if i < 35 else 1
    )
    escribir_corrida(raw, "r1", filas)
    t.generar_tablas(cargar_corridas(raw), sal)
    with open(sal / "t1_3_ttx_aislada.csv") as f:
        fila = next(csv.DictReader(f))
    assert fila["estado"].startswith("EXCLUIDA") and fila["media"] == ""


def test_formato_latex():
    assert formatear(float("nan"), 2) == "--" and formatear(3.14159, 2) == "3.14"
    assert formatear("a_b%", 2) == r"a\_b\%" and formatear(5, 2) == "5"
    import pandas as pd

    tex = a_latex(pd.DataFrame({"x_y": [1.23456], "n": [3]}), "c", "tab:x", {"x_y": 1})
    assert "x\\_y" in tex and "1.2" in tex and "1.23456" not in tex


def test_escribir_tabla_crea_ambos_archivos(tmp_path):
    import pandas as pd

    csv_, tex_ = escribir_tabla(
        pd.DataFrame({"a": [1.0]}), tmp_path / "x" / "t", caption="c", label="l"
    )
    assert csv_.exists() and tex_.exists()


def test_script_tablas(tmp_path, capsys):
    import importlib.util
    import sys

    from edge_parcial.config import RAIZ

    raw = tmp_path / "raw"
    escribir_corrida(raw, "r1", filas_red("r1", "esp32", "/stream", n=30))
    espec = importlib.util.spec_from_file_location(
        "tabs", RAIZ / "scripts" / "t1_2_1_3_tablas.py"
    )
    mod = importlib.util.module_from_spec(espec)
    sys.modules["tabs"] = mod
    espec.loader.exec_module(mod)
    assert mod.main(["--raw", str(raw), "--salida", str(tmp_path / "s")]) == 0
    assert (tmp_path / "s" / "t1_3_ttx_aislada.tex").exists()
    assert (
        mod.main(["--raw", str(tmp_path / "vacio"), "--salida", str(tmp_path / "s")])
        == 1
    )


def test_unidad_excluida_repetida_con_exito_no_duplica(tmp_path):
    from datos_sinteticos import escribir_corrida, filas_red

    from edge_parcial.analysis import tarea_1_2_1_3 as t12
    from edge_parcial.analysis.carga import cargar_corridas

    validez = {"droidcam": {"valida": False, "motivos": ["abandonada"]}}
    escribir_corrida(tmp_path, "a", filas_red("a", "droidcam", "/video", 30), fuentes=["droidcam"], validez=validez, corrida=1)  # fmt: skip
    escribir_corrida(tmp_path, "b", filas_red("b", "droidcam", "/video", 30), fuentes=["droidcam"], corrida=1)  # fmt: skip
    res = t12.resumenes(cargar_corridas(tmp_path))
    assert list(res["run_id"]) == ["b"]
    solo_mala = tmp_path / "x"
    escribir_corrida(solo_mala, "c", filas_red("c", "droidcam", "/video", 30), fuentes=["droidcam"], validez=validez, corrida=1)  # fmt: skip
    res2 = t12.resumenes(cargar_corridas(solo_mala))
    assert list(res2["run_id"]) == ["c"] and not res2["utilizable"].iloc[0]


def test_corrida_con_mas_de_5_pct_de_errores_se_excluye_aunque_diga_valida(tmp_path):
    from datos_sinteticos import escribir_corrida, filas_red

    from edge_parcial.analysis import tarea_1_2_1_3 as t12
    from edge_parcial.analysis.carga import cargar_corridas

    filas = filas_red("a", "droidcam", "/video", 40)
    for f in filas[-10:]:
        f["error"] = "ErrorProtocolo: respuesta HTML"
    escribir_corrida(tmp_path, "a", filas, fuentes=["droidcam"], corrida=1)
    res = t12.resumenes(cargar_corridas(tmp_path))
    assert not res["utilizable"].iloc[0] and "con error" in res["estado"].iloc[0]
