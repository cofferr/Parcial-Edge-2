"""Tarea 1.6 sobre una grabación sintética (escena estática con ruido + objeto en movimiento)."""

import importlib.util
import json
import sys

import cv2
import numpy as np
import pandas as pd
import pytest

from edge_parcial.acquisition.grabador import guion_estandar
from edge_parcial.acquisition.modelo import COLUMNAS_FRAMES
from edge_parcial.analysis import tarea_1_6 as t16
from edge_parcial.config import RAIZ

FPS = 20
PERIODO_NS = 1_000_000_000 // FPS
T0 = 10_000_000_000


def escena(i, activo, rng):
    img = np.full((120, 160), 90, np.uint8)
    if activo:  # bloque de 40x40 que se mueve cada fotograma
        x = (i * 13) % 100
        img[40:80, x : x + 40] = 230
    return np.clip(img + rng.normal(0, 1.2, img.shape), 0, 255).astype(np.uint8)


def grabar(raiz, fuentes=("local", "esp32"), valida=True, n_cal=2.0):
    run = "rec"
    carpeta = raiz / run
    guion = guion_estandar(n_cal, 2, 2.0, 2.0)
    t = T0
    segs = []
    for i, s in enumerate(guion):
        segs.append({"run_id": run, "idx": i, "tipo": s.tipo, "ciclo": s.ciclo,
                     "t_ini_ns": t, "t_fin_ns": t + int(s.duracion_s * 1e9)})  # fmt: skip
        t += int(s.duracion_s * 1e9)
    carpeta.mkdir(parents=True)
    pd.DataFrame(segs).to_csv(carpeta / "segmentos.csv", index=False)
    filas = []
    for f_i, fuente in enumerate(fuentes):
        rng = np.random.default_rng(f_i)
        (carpeta / fuente).mkdir()
        seq = 0
        for sg in segs:
            n = int((sg["t_fin_ns"] - sg["t_ini_ns"]) / PERIODO_NS)
            for k in range(n):
                img = escena(seq, sg["tipo"] == "actividad", rng)
                _ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 50])
                (carpeta / fuente / f"{seq:06d}.jpg").write_bytes(buf.tobytes())
                tt = sg["t_ini_ns"] + k * PERIODO_NS
                fila = {c: None for c in COLUMNAS_FRAMES}
                fila.update(run_id=run, source=fuente, endpoint="cv2.read" if fuente == "local" else "/stream",
                            condition="grabacion", seq=seq, warmup=0, conexion=0,
                            payload_bytes=int(buf.size), jpeg_valid=1, descartado=0,
                            **({"t_ready_ns": tt} if fuente == "local" else {"t_last_ns": tt}))  # fmt: skip
                filas.append(fila)
                seq += 1
    pd.DataFrame(filas).to_csv(carpeta / "frames.csv", index=False)
    meta = {
        "run_id": run, "valida": valida, "motivos_invalida": [] if valida else ["abortada"],
        "fuentes_usadas": list(fuentes),
        "validez_por_fuente": {f: {"valida": True, "motivos": []} for f in fuentes},
    }  # fmt: skip
    (carpeta / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return carpeta


def test_f_estatico_bajo_y_actividad_alta(tmp_path):
    r = t16.analizar_grabacion(grabar(tmp_path / "rec"), tmp_path / "out", guarda_s=0.2)
    assert not r["excluidas"] and len(r["resultados"]) == 2
    for res in r["resultados"]:
        assert (
            res["estatico"]["f_frames"] <= 0.12
        )  # calibrado con pocas muestras: margen de muestreo
        assert res["actividad"]["f_frames"] > 0.9  # el objeto se mueve cada fotograma
        assert res["actividad"]["f_bytes"] > res["estatico"]["f_bytes"]
        assert res["fps"] == pytest.approx(FPS, rel=0.02)
        assert res["p_real"] == pytest.approx(0.5, abs=0.001)


def test_formulas_D_A_y_f_de_p(tmp_path):
    r = t16.analizar_grabacion(grabar(tmp_path / "rec"), tmp_path / "out", guarda_s=0.2)
    res = r["resultados"][0]
    assert res["d_gb"] == pytest.approx(
        res["s_medio_bytes"] * res["fps"] * 2_592_000 / 1e9
    )
    fe, fa = res["estatico"]["f_bytes"], res["actividad"]["f_bytes"]
    assert t16.f_de_p(res, 0.05, "f_bytes") == pytest.approx(0.05 * fa + 0.95 * fe)
    ah = pd.read_csv(tmp_path / "out" / "t1_6_ahorro.csv")
    fila = ah[(ah["fuente"] == "local") & (ah["p"] == "5 %")].iloc[0]
    assert fila["a_gb"] == pytest.approx((1 - fila["f_bytes"]) * res["d_gb"])
    assert set(ah["p"]) == {"1 %", "5 %", "25 %", "real"}
    for p in ah["p"].unique():
        g = ah[ah["p"] == p]
        assert g[g["fuente"] == "TOTAL"]["a_gb"].iloc[0] == pytest.approx(g[g["fuente"] != "TOTAL"]["a_gb"].sum())  # fmt: skip


def test_tablas_figura_y_csv_sin_redondear(tmp_path):
    r = t16.analizar_grabacion(grabar(tmp_path / "rec"), tmp_path / "out", guarda_s=0.2)
    out = tmp_path / "out"
    for n in ("t1_6_calibracion", "t1_6_f", "t1_6_ahorro"):
        assert (out / f"{n}.csv").exists() and "tabular" in (
            out / f"{n}.tex"
        ).read_text()
    csv_f = pd.read_csv(out / "t1_6_f.csv")
    assert set(csv_f["tipo"]) == {"estatico", "actividad"}
    assert (out / "t1_6_barrido_t_area.csv").exists()
    assert r["barridos"]["f_frames_estatico"].between(0, 1).all()


def test_grabacion_invalida_o_sin_calibracion_no_se_analiza(tmp_path):
    with pytest.raises(t16.ErrorGrabacion):
        t16.analizar_grabacion(grabar(tmp_path / "a", valida=False), tmp_path / "o")
    r = t16.analizar_grabacion(
        grabar(tmp_path / "b", n_cal=0.2), tmp_path / "o", guarda_s=0.05
    )
    assert len(r["excluidas"]) == 2 and not r["resultados"]
    with pytest.raises(t16.ErrorGrabacion):
        t16.analizar_grabacion(tmp_path / "vacia", tmp_path / "o")


def test_script_analisis_con_figura(tmp_path, capsys):
    carpeta = grabar(tmp_path / "rec")
    espec = importlib.util.spec_from_file_location(
        "a16", RAIZ / "scripts" / "t1_6_analisis.py"
    )
    mod = importlib.util.module_from_spec(espec)
    sys.modules["a16"] = mod
    espec.loader.exec_module(mod)
    rc = mod.main(
        [
            "--grabacion",
            str(carpeta),
            "--salida",
            str(tmp_path / "s"),
            "--guarda-s",
            "0.2",
        ]
    )
    assert rc == 0 and (tmp_path / "s" / "t1_6_f_vs_umbral.png").stat().st_size > 5000
    assert mod.main(["--recordings", str(tmp_path / "nada")]) == 1
