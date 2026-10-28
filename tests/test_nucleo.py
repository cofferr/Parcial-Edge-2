"""Tarea 2.3: núcleo completo con fuentes simuladas, salidas del contrato y superposición."""

import csv
import json
import threading
import time
from dataclasses import replace

import numpy as np
import pytest

from edge_parcial.acquisition.pantalla import TECLA_Q
from edge_parcial.config import RUTA_EJEMPLO, cargar_config
from edge_parcial.edge.detector import ParamsDetector
from edge_parcial.nucleo import salidas
from edge_parcial.nucleo.config_p2 import FUENTES, ConfigP2
from edge_parcial.nucleo.fuentes import EntradaSimulada
from edge_parcial.nucleo.modelo import Decision, VotoVentana
from edge_parcial.nucleo.nucleo import ErrorNucleo, Nucleo
from edge_parcial.nucleo.ventanas import ANCHO, dibujar_fuente, ejecutar_ventanas

TAM = (32, 24)


def cfg_p2(n=3, ventana_s=0.5, gracia_s=0.1):
    base = cargar_config(RUTA_EJEMPLO)
    p = ParamsDetector(t_pix=10, t_area=0.02, tam=TAM)
    return ConfigP2(
        base=base, n_quorum=n, ventana_s=ventana_s, gracia_s=gracia_s, timeout_fog_s=0.5,
        detector=dict.fromkeys(FUENTES, p), eventos_csv=None, estado_json=None,
    )  # fmt: skip


def quieta(t_s):
    return np.full((TAM[1], TAM[0]), 120, np.uint8)


def movimiento(t_s):
    img = np.full((TAM[1], TAM[0]), 120, np.uint8)
    x = int(t_s * 30) % 20
    img[4:12, x : x + 8] = 250
    return img


def correr(tmp_path, escenario, segundos=3.2, **kw):
    """escenario: fuente -> (generador, caida_desde_s). Devuelve (filas de eventos, núcleo)."""
    entradas = {
        f: EntradaSimulada(f, g, fps=20, caida_desde_s=caida)
        for f, (g, caida) in escenario.items()
    }
    lineas = []
    nuc = Nucleo(
        cfg_p2(), entradas, "t", tmp_path / "eventos.csv", tmp_path / "estado.json",
        consola=lineas.append, latido_s=0.2, **kw,
    )  # fmt: skip
    nuc.iniciar()
    time.sleep(segundos)
    nuc.detener()
    with open(tmp_path / "eventos.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f)), nuc, lineas


def alertas(filas, desde=2):
    """Alertas de las ventanas estabilizadas (la 0 y la 1 incluyen el arranque)."""
    return [int(f["alerta"]) for f in filas if int(f["ventana"]) >= desde]


def test_tres_fuentes_con_movimiento_alertan_y_el_log_dice_alerta(tmp_path):
    filas, nuc, lineas = correr(tmp_path, dict.fromkeys(FUENTES, (movimiento, None)))
    assert len(filas) >= 4
    assert all(a == 1 for a in alertas(filas))
    assert all(f["Q"] == "2" and f["n_true"] == "3" for f in filas if int(f["ventana"]) >= 2)  # fmt: skip
    assert any("ALERTA" in ln for ln in lineas[2:])
    assert nuc.q == 2


def test_dos_con_movimiento_y_una_caida_alertan(tmp_path):
    esc = {"esp32": (movimiento, None), "droidcam": (movimiento, None), "local": (quieta, 0.0)}  # fmt: skip
    filas, _, _ = correr(tmp_path, esc)
    assert all(a == 1 for a in alertas(filas))
    fila = next(f for f in filas if int(f["ventana"]) == 3)
    assert (fila["voto_local"], fila["bandera_local"]) == ("0", "sin_datos")
    assert fila["n_true"] == "2"


def test_un_solo_voto_no_alerta_y_cero_tampoco(tmp_path):
    esc = {"esp32": (movimiento, None), "droidcam": (quieta, None), "local": (quieta, None)}  # fmt: skip
    (tmp_path / "uno").mkdir()
    filas, _, lineas = correr(tmp_path / "uno", esc)
    assert all(a == 0 for a in alertas(filas))
    assert all(f["n_true"] == "1" for f in filas if int(f["ventana"]) >= 2)
    assert not any("ALERTA" in ln for ln in lineas)
    (tmp_path / "cero").mkdir()
    filas, _, _ = correr(tmp_path / "cero", dict.fromkeys(FUENTES, (quieta, None)), 2.2)
    assert all(a == 0 for a in alertas(filas)) and all(f["n_true"] == "0" for f in filas[2:])  # fmt: skip


def test_rejilla_comun_y_estado_json_con_las_seis_claves(tmp_path):
    filas, _, _ = correr(tmp_path, dict.fromkeys(FUENTES, (movimiento, None)), 2.2)
    ini = [int(f["t_ventana_ini_ns"]) for f in filas]
    assert ini == [
        ini[0] + 500_000_000 * i for i in range(len(ini))
    ]  # rejilla única de 0,5 s
    estado = json.loads((tmp_path / "estado.json").read_text())
    assert set(estado) == set(salidas.COMPONENTES_ESTADO)
    for c in estado.values():
        assert set(c) == {"vivo", "fps", "ultima_marca", "errores_recientes"}
    assert estado["nucleo"]["vivo"] is False  # último latido, tras detener()
    assert estado["camara_esp32"]["ultima_marca"] is not None


def test_n_distinto_del_numero_de_fuentes_es_error(tmp_path):
    entradas = {"esp32": EntradaSimulada("esp32", quieta)}
    with pytest.raises(ErrorNucleo):
        Nucleo(cfg_p2(), entradas, "t", tmp_path / "e.csv", None)


def test_q_sale_de_n_de_la_config(tmp_path):
    cfg = replace(cfg_p2(), n_quorum=3)
    entradas = {f: EntradaSimulada(f, quieta) for f in FUENTES}
    assert Nucleo(cfg, entradas, "t", tmp_path / "e.csv", None).q == 2


def test_la_captura_de_capas_registra_marcas(tmp_path):
    from edge_parcial.capas.registro import RegistroCapas

    capas = RegistroCapas(tmp_path / "capas")
    _, _, _ = correr(
        tmp_path, dict.fromkeys(FUENTES, (movimiento, None)), 2.0, capas=capas
    )
    with open(capas.ruta_fotogramas, encoding="utf-8") as f:
        fotos = list(csv.DictReader(f))
    assert fotos and all(int(r["t_edge_fin_ns"]) >= int(r["t_edge_ini_ns"]) >= int(r["t_ready_ns"]) for r in fotos)  # fmt: skip
    with open(capas.ruta_ventanas, encoding="utf-8") as f:
        vent = list(csv.DictReader(f))
    assert vent and all(
        int(r["t_decision_ns"]) >= int(r["t_voto_ns_esp32"]) for r in vent
    )


# --- salidas -----------------------------------------------------------------------


def decision(alerta=True, k=3):
    votos = {f: VotoVentana(f, k, alerta, "movimiento" if alerta else "quieto", 0.5, 9, 10) for f in FUENTES}  # fmt: skip
    return Decision(k, 5_000, 2, votos, 3 if alerta else 0, alerta, 20, "2026-10-28T10:00:00.123456-05:00")  # fmt: skip


def test_eventos_csv_cabecera_una_vez_solo_anade_y_flush_por_fila(tmp_path):
    ruta = tmp_path / "eventos.csv"
    e = salidas.EventosCSV(ruta, "run1")
    e.escribir(decision())
    leido = (
        ruta.read_text().splitlines()
    )  # sin cerrar: ya está en disco (flush por fila)
    assert leido[0].split(",") == salidas.COLUMNAS_EVENTOS and len(leido) == 2
    e.cerrar()
    e2 = salidas.EventosCSV(ruta, "run2")
    e2.escribir(decision(False, 4))
    e2.cerrar()
    with open(ruta, encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    assert [r["run_id"] for r in filas] == ["run1", "run2"] and filas[1][
        "alerta"
    ] == "0"
    assert ruta.read_text().count("run_id,ts_wall") == 1


def test_eventos_csv_rechaza_otra_cabecera(tmp_path):
    ruta = tmp_path / "e.csv"
    ruta.write_text("a,b\n1,2\n")
    with pytest.raises(salidas.ErrorEsquema):
        salidas.EventosCSV(ruta, "r")


def test_linea_log_tiene_alerta_solo_si_hay_alerta():
    assert "ALERTA" in salidas.linea_log(decision(True))
    assert "ALERTA" not in salidas.linea_log(decision(False))
    assert "votos 3/3 Q=2" in salidas.linea_log(decision(True))


def test_estado_json_atomico_el_lector_nunca_ve_un_archivo_a_medias(tmp_path):
    ruta = tmp_path / "estado.json"
    salidas.escribir_atomico(
        ruta, salidas.estado_completo({}, salidas.entrada_estado(True))
    )
    parar, malos = threading.Event(), []

    def lector():
        while not parar.is_set():
            try:
                json.loads(ruta.read_text())
            except ValueError:
                malos.append(1)

    t = threading.Thread(target=lector)
    t.start()
    for i in range(300):
        salidas.escribir_atomico(ruta, salidas.estado_completo({}, salidas.entrada_estado(True, fps=i, errores=["x" * 5000])))  # fmt: skip
    parar.set()
    t.join()
    assert malos == []
    assert [p.name for p in tmp_path.iterdir()] == ["estado.json"]  # sin temporales


# --- superposición --------------------------------------------------------------------


def test_dibujar_fuente_muestra_banner_solo_con_alerta():
    img = np.full((240, 320, 3), 100, np.uint8)
    sin = dibujar_fuente(img, "esp32", True, "movimiento", 5, 2, 2, False)
    con = dibujar_fuente(img, "esp32", True, "movimiento", 5, 2, 2, True)
    assert sin.shape == con.shape == (480, ANCHO, 3)

    def rojo(a):
        return int(np.sum(np.all(a == (40, 40, 220), axis=2)))

    assert rojo(con) > 10_000 > rojo(sin) or rojo(con) > rojo(sin) + 10_000
    vacia = dibujar_fuente(None, "local", None, None, None, 2, None, False)
    assert vacia.shape[1] == ANCHO


class PantallaFalsa:
    def __init__(self, tecla_tras):
        self.mostradas, self.hilos, self.n, self.tecla_tras = {}, set(), 0, tecla_tras

    def mostrar(self, nombre, frame):
        self.hilos.add(threading.current_thread().name)
        self.mostradas.setdefault(nombre, []).append(frame.shape)

    def tecla(self, ms):
        self.n += 1
        return TECLA_Q if self.n >= self.tecla_tras else -1

    def visible(self, nombre):
        return True

    def cerrar(self):
        pass


def test_ventanas_en_el_hilo_principal_con_las_tres_fuentes(tmp_path):
    entradas = {f: EntradaSimulada(f, movimiento, fps=20) for f in FUENTES}
    nuc = Nucleo(
        cfg_p2(), entradas, "t", tmp_path / "e.csv", None, consola=lambda s: None
    )
    pantalla = PantallaFalsa(tecla_tras=40)
    with nuc:
        motivo = ejecutar_ventanas(nuc, pantalla, espera_ms=1)
    assert motivo == "tecla q"
    assert set(pantalla.mostradas) == {f"Quorum {f}" for f in FUENTES}
    assert pantalla.hilos == {threading.current_thread().name}
