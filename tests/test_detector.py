"""Tarea 2.2: detector de movimiento, voto por ventana, calibración y config."""

import math
import re

import numpy as np
import pandas as pd
import pytest

from edge_parcial.config import RUTA_EJEMPLO, ErrorConfig
from edge_parcial.edge import calibracion as cal
from edge_parcial.edge.detector import (
    BANDERA_CAMBIO_GLOBAL,
    BANDERA_MOVIMIENTO,
    BANDERA_QUIETO,
    BANDERA_SIN_DATOS,
    BANDERA_TAPADA,
    MS_A_NS,
    S_A_NS,
    DetectorMovimiento,
    ParamsDetector,
    ResultadoFotograma,
    votar,
)
from edge_parcial.nucleo import config_p2

TAM = (32, 24)
P = ParamsDetector(t_pix=10, t_area=0.02, tam=TAM)


def escena(
    valor: int = 120, bloque: tuple[int, int] | None = None, tam=TAM
) -> np.ndarray:
    """Imagen gris plana; `bloque` = (lado, valor) pinta un cuadrado brillante."""
    img = np.full((tam[1], tam[0]), valor, np.uint8)
    if bloque:
        lado, v = bloque
        img[:lado, :lado] = v
    return img


def r(t_ms, **kw) -> ResultadoFotograma:
    base = {
        "t_ns": t_ms * MS_A_NS, "evaluado": True, "fraccion": 0.0, "luminancia": 120.0,
        "movimiento": False, "cambio_global": False, "tapada": False,
    }  # fmt: skip
    return ResultadoFotograma(**{**base, **kw})


def test_sin_referencia_no_se_evalua_hasta_200_ms():
    d = DetectorMovimiento(P)
    assert not d.procesar(escena(), 0).evaluado
    assert not d.procesar(escena(), 100 * MS_A_NS).evaluado  # edad 100 ms < 200 ms
    assert d.procesar(escena(), 200 * MS_A_NS).evaluado


def test_referencia_es_ultimo_fotograma_con_edad_minima():
    d = DetectorMovimiento(P)
    d.procesar_preparado(escena(100), 0)
    d.procesar_preparado(escena(110), 150 * MS_A_NS)
    d.procesar_preparado(escena(120), 300 * MS_A_NS)
    # t=400: la referencia es el de t=150 (edad 250 >= 200), no el de t=300 (edad 100)
    res = d.procesar_preparado(escena(120), 400 * MS_A_NS)
    assert res.fraccion == 0.0  # contra 110 el cambio es 10, no > t_pix = 10
    d2 = DetectorMovimiento(P)
    d2.procesar_preparado(escena(100), 0)
    d2.procesar_preparado(escena(160), 150 * MS_A_NS)
    res = d2.procesar_preparado(escena(160), 400 * MS_A_NS)
    assert res.fraccion == 0.0  # igual al de t=150


def test_movimiento_local_si_supera_t_area():
    d = DetectorMovimiento(P)
    d.procesar_preparado(escena(), 0)
    res = d.procesar_preparado(escena(bloque=(6, 255)), 250 * MS_A_NS)
    assert res.movimiento and res.fraccion == pytest.approx(36 / (32 * 24))
    quieto = d.procesar_preparado(escena(bloque=(6, 255)), 600 * MS_A_NS)
    assert not quieto.movimiento


def test_cambio_global_de_luminancia_no_es_movimiento():
    d = DetectorMovimiento(P)
    d.procesar_preparado(escena(100), 0)
    res = d.procesar_preparado(escena(200), 250 * MS_A_NS)
    assert res.cambio_global and not res.movimiento


def test_cambio_global_por_fraccion_alta():
    d = DetectorMovimiento(P)
    d.procesar_preparado(escena(100), 0)
    # 70 % de la imagen cambia, pero la luminancia media varía poco (+/-)
    img = escena(100)
    img[:17, :] = 130  # 17/24 = 70.8 % de filas
    res = d.procesar_preparado(img, 250 * MS_A_NS)
    assert res.fraccion > 0.6 and res.cambio_global and not res.movimiento


def test_tapada_tras_un_segundo_de_oscuridad():
    d = DetectorMovimiento(P)
    d.procesar_preparado(escena(120), 0)
    marcas = [
        d.procesar_preparado(escena(5), t * MS_A_NS) for t in range(250, 2000, 250)
    ]
    assert not marcas[0].tapada  # oscuro desde hace 0 s
    assert not marcas[3].tapada  # t=1000: exactamente 750 ms oscuro
    assert marcas[4].tapada  # t=1250: 1000 ms oscuro
    assert all(not m.movimiento for m in marcas)
    despues = d.procesar_preparado(escena(120), 2500 * MS_A_NS)
    assert not despues.tapada  # la luz vuelve; ese salto es cambio global
    assert despues.cambio_global and not despues.movimiento


def test_voto_umbral_y_banderas():
    quieto = [r(i * 100) for i in range(10)]
    assert votar(quieto, 0.3) == (False, BANDERA_QUIETO, 0.0)
    mov = [r(i * 100, movimiento=i < 3) for i in range(10)]
    assert votar(mov, 0.3) == (True, BANDERA_MOVIMIENTO, 0.3)  # >= umbral
    assert votar(mov[:2] + quieto, 0.3)[0] is False
    glob = quieto[:5] + [r(600, cambio_global=True)]
    assert votar(glob, 0.3)[1] == BANDERA_CAMBIO_GLOBAL


def test_voto_sin_fotogramas_es_false_sin_datos():
    assert votar([], 0.3)[:2] == (False, BANDERA_SIN_DATOS)
    solo_sin_ref = [r(0, evaluado=False, fraccion=math.nan)]
    assert votar(solo_sin_ref, 0.3)[:2] == (False, BANDERA_SIN_DATOS)


def test_voto_tapada_es_false():
    res = [r(0, movimiento=True), r(100, movimiento=True, tapada=True)]
    assert votar(res, 0.3)[:2] == (False, BANDERA_TAPADA)


def test_no_se_arrastra_el_voto_anterior():
    ventana1 = [r(i * 100, movimiento=True) for i in range(5)]
    assert votar(ventana1, 0.3)[0] is True
    assert votar([], 0.3)[0] is False  # ventana siguiente vacía


# --- calibración sintética -----------------------------------------------------


def secuencia_sintetica(fps=20, segundos=40, mover_desde=None, ruido=2, semilla=0):
    rng = np.random.default_rng(semilla)
    t = (np.arange(segundos * fps) * S_A_NS // fps).astype(np.int64)
    grises = []
    for ti in t:
        g = escena(120).astype(np.int16) + rng.integers(
            -ruido, ruido + 1, (TAM[1], TAM[0])
        )
        if mover_desde is not None and ti >= mover_desde * S_A_NS:
            x = int((ti / 5e7) % 20)
            g[4:12, x : x + 8] = 250
        grises.append(np.clip(g, 0, 255).astype(np.uint8))
    return cal.SecuenciaFuente("sim", t, grises)


def test_calibrar_fuente_cumple_el_1_por_ciento():
    seq = secuencia_sintetica()
    params, diag = cal.calibrar_fuente(seq, 0, 30 * S_A_NS, ParamsDetector(1.0, 0.0, tam=TAM), guarda_s=2)  # fmt: skip
    assert diag["estaticos_con_movimiento"] <= 0.01
    assert diag["ventanas_estaticas_voto_true"] <= 0.01
    assert params.umbral_voto >= 0.3
    assert params.t_pix >= 1


def test_calibrar_sin_fotogramas_falla():
    seq = secuencia_sintetica(fps=5, segundos=1)
    with pytest.raises(cal.ErrorCalibracion):
        cal.calibrar_fuente(seq, 0, S_A_NS, guarda_s=0)


def test_evaluar_y_matriz_de_confusion():
    seq = secuencia_sintetica(segundos=40, mover_desde=20)
    params, _ = cal.calibrar_fuente(seq, 0, 18 * S_A_NS, ParamsDetector(1.0, 0.0, tam=TAM), guarda_s=2)  # fmt: skip
    res = cal.reproducir(seq, params)
    segmentos = pd.DataFrame(
        {
            "tipo": ["estatico", "actividad"],
            "t_ini_ns": [0, 20 * S_A_NS],
            "t_fin_ns": [20 * S_A_NS, 40 * S_A_NS],
        }
    )
    v = cal.evaluar({"sim": res}, {"sim": params}, segmentos, q=1)
    m = cal.matriz_confusion(v, "voto_sim")
    assert m["FP"] == 0 and m["VN"] > 0
    assert m["VP"] >= m["ventanas_actividad"] - 2  # tolera la guarda y el arranque
    assert cal.matriz_confusion(v, "alerta")["tasa_FP"] == 0


def test_etiqueta_ventana_respeta_guarda_y_limites():
    seg = pd.DataFrame(
        {"tipo": ["estatico"], "t_ini_ns": [0], "t_fin_ns": [10 * S_A_NS]}
    )
    assert cal.etiqueta_ventana(S_A_NS, 2 * S_A_NS, seg, 1.0) == "estatico"
    assert cal.etiqueta_ventana(0, S_A_NS, seg, 1.0) is None  # dentro de la guarda
    assert cal.etiqueta_ventana(9_500_000_000, 10_500_000_000, seg, 1.0) is None


# --- config --------------------------------------------------------------------


def test_params_detector_desde_config():
    datos = {"detector": {"umbral_global": 0.5, "esp32": {"t_pix": 3, "t_area": 0.1, "umbral_voto": 0.4}}}  # fmt: skip
    p = config_p2.params_detector(datos, "esp32")
    assert (p.t_pix, p.t_area, p.umbral_voto, p.umbral_global) == (3, 0.1, 0.4, 0.5)
    with pytest.raises(ErrorConfig, match="detector.droidcam"):
        config_p2.params_detector(datos, "droidcam")
    with pytest.raises(ErrorConfig, match="umbral_voto"):
        config_p2.params_detector({"detector": {"local": {"t_pix": 1, "t_area": 0.1}}}, "local")  # fmt: skip


def test_escribir_secciones_detector_reemplaza_sin_duplicar(tmp_path):
    ruta = tmp_path / "c.toml"
    ruta.write_text(RUTA_EJEMPLO.read_text(encoding="utf-8"))
    nuevo = {"esp32": ParamsDetector(5.0, 0.2, 0.3)}
    config_p2.escribir_secciones_detector(ruta, nuevo)
    config_p2.escribir_secciones_detector(
        ruta, {"esp32": ParamsDetector(7.0, 0.25, 0.4)}
    )
    import tomllib

    datos = tomllib.loads(ruta.read_text(encoding="utf-8"))
    assert datos["detector"]["esp32"] == {
        "t_pix": 7.0,
        "t_area": 0.25,
        "umbral_voto": 0.4,
    }
    assert len(re.findall(r"^\[detector.esp32\]", ruta.read_text(), re.MULTILINE)) == 1
    assert "[quorum]" in ruta.read_text()  # el resto queda intacto


def test_cargar_config_p2_exige_n(tmp_path):
    ruta = tmp_path / "c.toml"
    ruta.write_text(RUTA_EJEMPLO.read_text(encoding="utf-8").replace("n = 3\n", ""))
    config_p2.escribir_secciones_detector(
        ruta, {f: ParamsDetector(1.0, 0.1, 0.3) for f in config_p2.FUENTES}
    )
    with pytest.raises(ErrorConfig, match=r"\[quorum\]"):
        config_p2.cargar_config_p2(ruta)
    ruta.write_text(ruta.read_text().replace("[quorum]", "[quorum]\nn = 3"))
    cfg = config_p2.cargar_config_p2(ruta)
    assert cfg.n_quorum == 3 and set(cfg.detector) == set(config_p2.FUENTES)
    assert cfg.gracia_s == 0.25
