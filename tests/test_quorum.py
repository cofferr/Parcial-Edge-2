"""Tarea 2.3: fórmula de Q, rejilla de ventanas, voto del edge y decisión del fog."""

import math

import numpy as np
import pytest

from edge_parcial.edge.detector import (
    BANDERA_CAMBIO_GLOBAL,
    BANDERA_MOVIMIENTO,
    BANDERA_SIN_DATOS,
    ParamsDetector,
)
from edge_parcial.edge.trabajador import TrabajadorEdge
from edge_parcial.fog.decision import BANDERA_CAIDA, Fog
from edge_parcial.fog.quorum import decidir, quorum
from edge_parcial.fog.rejilla import Rejilla
from edge_parcial.nucleo.modelo import FotogramaEdge, VotoVentana

S = 1_000_000_000
TAM = (32, 24)
P = ParamsDetector(t_pix=10, t_area=0.02, tam=TAM)


@pytest.mark.parametrize(
    "n, esperado", [(1, 1), (2, 2), (3, 2), (4, 3), (5, 3), (6, 4), (7, 4)]
)
def test_quorum_de_1_a_7(n, esperado):
    assert quorum(n) == esperado == n // 2 + 1


def test_quorum_n3_es_2_y_rechaza_n_invalido():
    assert quorum(3) == math.floor(3 / 2) + 1 == 2
    for malo in (0, -1):
        with pytest.raises(ValueError):
            quorum(malo)


@pytest.mark.parametrize(
    "votos, alerta",
    [
        ([True] * 3, True),
        ([True, True, False], True),
        ([True, False, False], False),
        ([False] * 3, False),
    ],
)
def test_alerta_con_3_2_1_y_0_votos(votos, alerta):
    n_true, resultado = decidir(votos, quorum(3))
    assert n_true == sum(votos) and resultado is alerta


# --- rejilla ---------------------------------------------------------------------


def test_rejilla_asigna_por_t_ready_y_el_limite_va_a_la_ventana_siguiente():
    g = Rejilla(1000 * S, S)
    assert g.indice(1000 * S) == 0
    assert g.indice(1000 * S + S - 1) == 0
    assert g.indice(1001 * S) == 1  # exactamente en el límite: pertenece a la nueva
    assert g.indice(999 * S) == -1  # anterior a t0
    assert (g.inicio(3), g.fin(3)) == (1003 * S, 1004 * S)


# --- edge: voto por ventana con reloj controlado ----------------------------------


class Reloj:
    def __init__(self, t=0):
        self.t = t

    def __call__(self):
        return self.t


def img(valor=120, bloque=None):
    a = np.full((TAM[1], TAM[0]), valor, np.uint8)
    if bloque:
        a[:bloque, :bloque] = 255
    return a


def trabajador(reloj, votos, filas=None, gracia_ns=0):
    return TrabajadorEdge(
        "esp32", P, Rejilla(0, S), gracia_ns, votos.append,
        None if filas is None else filas.append, reloj=reloj,
    )  # fmt: skip


def fotograma(t_ms, seq, imagen):
    return FotogramaEdge("esp32", seq, t_ms * 1_000_000, imagen)


def test_ventana_sin_fotogramas_vota_false_sin_datos_y_no_arrastra_el_anterior():
    reloj = Reloj()
    votos = []
    w = trabajador(reloj, votos)
    # ventana 0 con movimiento continuo
    for i, t in enumerate(range(0, 1000, 100)):
        w._procesar(fotograma(t, i, img(bloque=2 + (i // 2 % 2) * 8)))
    reloj.t = 1 * S
    w._cerrar_vencidas()
    assert votos[0].voto is True and votos[0].bandera == BANDERA_MOVIMIENTO
    # la ventana 1 no recibe nada
    reloj.t = 2 * S
    w._cerrar_vencidas()
    assert votos[1].voto is False and votos[1].bandera == BANDERA_SIN_DATOS
    assert votos[1].n_fotogramas == 0


def test_fotograma_en_el_limite_entre_ventanas_cuenta_en_la_siguiente():
    reloj = Reloj()
    votos, filas = [], []
    w = trabajador(reloj, votos, filas)
    w._procesar(fotograma(900, 0, img()))
    w._procesar(fotograma(1000, 1, img()))  # t_ready == fin de la ventana 0
    assert [f["ventana"] for f in filas] == [0, 1]
    reloj.t = 3 * S
    w._cerrar_vencidas()
    assert [v.n_fotogramas for v in votos] == [1, 1, 0]  # el de t=1000 no está en la 0


def test_fotograma_tardio_se_registra_y_no_entra_al_voto():
    reloj = Reloj()
    votos, filas = [], []
    w = trabajador(reloj, votos, filas)
    w._procesar(fotograma(100, 0, img()))
    reloj.t = 1 * S
    w._cerrar_vencidas()  # la ventana 0 ya está votada
    w._procesar(
        fotograma(950, 1, img(bloque=10))
    )  # t_ready en la ventana 0, llega tarde
    assert filas[-1]["ventana"] == 0 and filas[-1]["tardio"] == 1
    assert votos[0].n_fotogramas == 1 and w.tardios == 1


def test_gracia_retrasa_la_emision_del_voto():
    reloj = Reloj()
    votos = []
    w = trabajador(reloj, votos, gracia_ns=250_000_000)
    reloj.t = 1 * S + 100_000_000
    w._cerrar_vencidas()
    assert votos == []
    reloj.t = 1 * S + 250_000_000
    w._cerrar_vencidas()
    assert len(votos) == 1


def test_cambio_global_de_luminancia_no_produce_voto():
    reloj = Reloj()
    votos = []
    w = trabajador(reloj, votos)
    for i, t in enumerate(range(0, 1000, 100)):
        w._procesar(fotograma(t, i, img(60 if i < 5 else 200)))  # salto brusco de luz
    reloj.t = 1 * S
    w._cerrar_vencidas()
    assert votos[0].voto is False and votos[0].bandera == BANDERA_CAMBIO_GLOBAL


def test_fotograma_anterior_a_t0_se_ignora():
    reloj = Reloj(5 * S)
    votos = []
    w = TrabajadorEdge("esp32", P, Rejilla(5 * S, S), 0, votos.append, reloj=reloj)
    w._procesar(fotograma(4900, 0, img()))
    assert w._buffer == {}


# --- fog ---------------------------------------------------------------------------


def v(src, k, voto, bandera="x"):
    return VotoVentana(src, k, voto, bandera, 0.0, 5, 1)


def fog(reloj=None, salida=None):
    return Fog(
        ("esp32", "droidcam", "local"), quorum(3), Rejilla(0, S), 0, S,
        (salida if salida is not None else []).append, reloj or Reloj(),
    )  # fmt: skip


def test_fuente_caida_cuenta_false_y_dos_votos_bastan():
    f = fog()
    d = f.decidir_ventana(
        0, {"esp32": v("esp32", 0, True), "droidcam": v("droidcam", 0, True)}
    )
    assert d.caidas == ["local"] and d.votos["local"].bandera == BANDERA_CAIDA
    assert d.n_true == 2 and d.alerta and d.q == 2


def test_una_sola_fuente_viva_no_alcanza_el_quorum():
    d = fog().decidir_ventana(0, {"local": v("local", 0, True)})
    assert d.n_true == 1 and not d.alerta and sorted(d.caidas) == ["droidcam", "esp32"]


def test_fuente_tapada_cuenta_false():
    votos = {
        "esp32": v("esp32", 0, True),
        "droidcam": v("droidcam", 0, False, "tapada"),
        "local": v("local", 0, False, "tapada"),
    }
    assert not fog().decidir_ventana(0, votos).alerta


def test_fog_decide_en_orden_con_los_tres_votos_y_con_timeout():
    reloj, salida = Reloj(), []
    f = fog(reloj, salida)
    for s in ("esp32", "droidcam", "local"):
        f.recibir(v(s, 0, True))
    f.recibir(v("esp32", 1, True))  # la ventana 1 queda incompleta
    # procesa la cola a mano (sin hilo)
    while not f.cola.empty():
        voto = f.cola.get_nowait()
        f._pendientes.setdefault(voto.ventana, {})[voto.source] = voto
    reloj.t = 1 * S  # fin de la ventana 0 (+gracia 0 +timeout 1 s aún no)
    f._decidir_listas()
    assert [d.ventana for d in salida] == [0] and salida[0].alerta
    reloj.t = 3 * S  # fin ventana 1 (2 s) + timeout 1 s
    f._decidir_listas()
    assert [d.ventana for d in salida] == [0, 1]
    assert sorted(salida[1].caidas) == ["droidcam", "local"] and not salida[1].alerta
    assert salida[1].t_decision_ns == 3 * S  # sellado al decidir


def test_un_fotograma_malo_no_mata_al_hilo_del_edge():
    import time

    votos = []
    w = TrabajadorEdge("esp32", P, Rejilla(time.perf_counter_ns(), S), 0, votos.append)
    w.start()
    w.encolar(
        FotogramaEdge("esp32", 0, time.perf_counter_ns(), None)
    )  # imagen inválida
    w.encolar(FotogramaEdge("esp32", 1, time.perf_counter_ns(), img()))
    time.sleep(0.3)
    w.detener()
    w.join(2)
    assert len(w.errores) == 1 and w.fotogramas == 1
