"""Filtro por diferencia con el último transmitido, con secuencias sintéticas."""

import itertools

import numpy as np
import pytest

from edge_parcial import filtro


def base(valor=100, tam=(120, 160)):
    return np.full(tam, valor, np.uint8)


def prep_seq(imgs):
    return [filtro.preparar(i) for i in imgs]


def test_preparar_gris_tamano_comun():
    bgr = np.zeros((1080, 1920, 3), np.uint8)
    assert filtro.preparar(bgr).shape == (120, 160)
    assert filtro.preparar(np.zeros((240, 320), np.uint8)).shape == (120, 160)


def test_estatica_solo_transmite_el_primero():
    m = filtro.simular(prep_seq([base()] * 30), t_pix=2, t_area=0.01)
    assert m.tolist() == [True] + [False] * 29


def test_ruido_calibrado_no_dispara():
    rng = np.random.default_rng(0)
    seq = prep_seq(
        [
            np.clip(base() + rng.normal(0, 2, (120, 160)), 0, 255).astype(np.uint8)
            for _ in range(60)
        ]
    )
    t_pix = filtro.calibrar_t_pix(seq)
    assert t_pix >= 1
    t_area, barrido = filtro.elegir_t_area(seq, t_pix)
    m = filtro.simular(seq, t_pix, t_area)
    assert m[1:].mean() <= 0.01
    assert all(0 <= f <= 1 for _, f in barrido)


def test_cambio_brusco_se_transmite_y_actualiza_referencia():
    seq = prep_seq([base(50)] * 5 + [base(200)] * 5)
    m = filtro.simular(seq, t_pix=10, t_area=0.05)
    assert m.tolist() == [
        True,
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
        False,
    ]


def test_cambio_lento_se_detecta_por_referencia_al_ultimo_transmitido():
    # Deriva de 1 nivel por fotograma: contra el ANTERIOR nunca supera t_pix=5,
    # contra el último transmitido sí acaba superándolo.
    seq = prep_seq([base(50 + i) for i in range(40)])
    m = filtro.simular(seq, t_pix=5, t_area=0.5)
    assert m.sum() > 3 and m[0]
    contra_anterior = [
        filtro.fraccion_cambiada(a, b, 5) for a, b in itertools.pairwise(seq)
    ]
    assert max(contra_anterior) == 0.0


def test_objeto_pequeno_respeta_t_area():
    img = base(50)
    img2 = img.copy()
    img2[:24, :32] = 250  # 4 % del área
    seq = prep_seq([img, img2])
    assert filtro.simular(seq, 10, 0.10).tolist() == [True, False]
    assert filtro.simular(seq, 10, 0.02).tolist() == [True, True]


def test_calibracion_con_pocos_fotogramas_falla():
    with pytest.raises(ValueError):
        filtro.calibrar_t_pix(prep_seq([base()]))


def test_elegir_t_area_sin_solucion_no_inventa():
    rng = np.random.default_rng(1)
    seq = prep_seq(
        [rng.integers(0, 255, (120, 160), dtype=np.uint8) for _ in range(20)]
    )
    with pytest.raises(ValueError):
        filtro.elegir_t_area(seq, t_pix=1, candidatos=[0.001, 0.01])
