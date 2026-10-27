"""Pruebas de la Tarea 1.1 con capturas y pantalla falsas (sin hardware)."""

import importlib.util
import sys
import threading
import time

import numpy as np

from edge_parcial.acquisition.pantalla import TECLA_Q
from edge_parcial.acquisition.tres_fuentes import (
    FuenteVideo,
    VisorTresFuentes,
    fuentes_desde_config,
)
from edge_parcial.config import RAIZ, RUTA_EJEMPLO, cargar_config


class CapFalsa:
    def __init__(
        self,
        ancho=64,
        alto=48,
        abre=True,
        intervalo=0.005,
        fallar_desde=None,
        bloqueo=0.0,
    ):
        self.ancho, self.alto, self.abre = ancho, alto, abre
        self.intervalo, self.fallar_desde, self.bloqueo = (
            intervalo,
            fallar_desde,
            bloqueo,
        )
        self.lecturas = 0
        self.liberada = False
        self.hilo_creacion = threading.current_thread().name

    def isOpened(self):
        return self.abre

    def read(self):
        time.sleep(self.bloqueo or self.intervalo)
        self.lecturas += 1
        if self.fallar_desde is not None and self.lecturas > self.fallar_desde:
            return False, None
        return True, np.full((self.alto, self.ancho, 3), self.lecturas % 255, np.uint8)

    def release(self):
        self.liberada = True


class PantallaFalsa:
    def __init__(self, teclas=None, ocultar=None, tras=0):
        self.teclas = list(teclas or [])
        self.ocultar, self.tras = ocultar, tras
        self.mostradas: dict[str, list] = {}
        self.cerrada = False
        self.hilos = set()

    def mostrar(self, nombre, frame):
        self.hilos.add(threading.current_thread().name)
        self.mostradas.setdefault(nombre, []).append(frame.shape)

    def tecla(self, espera_ms):
        time.sleep(0.003)
        return self.teclas.pop(0) if self.teclas else -1

    def visible(self, nombre):
        n = sum(len(v) for v in self.mostradas.values())
        return not (self.ocultar == nombre and n > self.tras)

    def cerrar(self):
        self.cerrada = True


def fabrica_de(caps):
    def fabrica(origen):
        cap = caps[origen]
        cap.origen = origen
        cap.hilo_apertura = threading.current_thread().name
        return cap

    return fabrica


FUENTES = [
    FuenteVideo("local", 0, abrir_en_principal=True),
    FuenteVideo("esp32", "http://esp/stream"),
    FuenteVideo("droidcam", "http://dc/video"),
]


def caps_base(**kw):
    return {
        0: CapFalsa(**kw),
        "http://esp/stream": CapFalsa(320, 240),
        "http://dc/video": CapFalsa(128, 72),
    }


def test_cierra_con_q_y_libera_todo_ordenadamente():
    caps = caps_base()
    pantalla = PantallaFalsa(teclas=[-1] * 20 + [TECLA_Q])
    r = VisorTresFuentes(FUENTES, pantalla, fabrica_de(caps)).ejecutar()
    assert r["motivo_cierre"] == "tecla q" and pantalla.cerrada
    assert all(c.liberada for c in caps.values())
    assert set(pantalla.mostradas) == {"local", "esp32", "droidcam"}
    assert all(f["fotogramas"] > 0 for f in r["fuentes"].values())


def test_cierra_al_cerrar_una_ventana():
    caps = caps_base()
    pantalla = PantallaFalsa(ocultar="esp32", tras=30)
    r = VisorTresFuentes(FUENTES, pantalla, fabrica_de(caps)).ejecutar()
    assert r["motivo_cierre"] == "ventana cerrada"
    assert all(c.liberada for c in caps.values()) and pantalla.cerrada


def test_las_ventanas_se_dibujan_en_el_hilo_principal():
    pantalla = PantallaFalsa(teclas=[-1] * 5 + [TECLA_Q])
    VisorTresFuentes(FUENTES, pantalla, fabrica_de(caps_base())).ejecutar()
    assert pantalla.hilos == {threading.current_thread().name}


def test_la_camara_local_se_abre_en_el_hilo_principal_y_las_de_red_en_su_hilo():
    caps = caps_base()
    VisorTresFuentes(
        FUENTES, PantallaFalsa(teclas=[-1] * 5 + [TECLA_Q]), fabrica_de(caps)
    ).ejecutar()
    assert caps[0].hilo_apertura == threading.current_thread().name
    assert caps["http://esp/stream"].hilo_apertura.startswith("cv2-esp32")


def test_una_fuente_que_no_abre_no_tumba_a_las_demas():
    caps = caps_base()
    caps["http://esp/stream"] = CapFalsa(abre=False)
    pantalla = PantallaFalsa(teclas=[-1] * 20 + [TECLA_Q])
    r = VisorTresFuentes(FUENTES, pantalla, fabrica_de(caps)).ejecutar()
    assert r["fuentes"]["esp32"]["error"] == "no se pudo abrir la fuente"
    assert (
        r["fuentes"]["local"]["fotogramas"] > 0
        and r["fuentes"]["droidcam"]["fotogramas"] > 0
    )
    assert "esp32" in pantalla.mostradas and caps["http://esp/stream"].liberada


def test_perdida_de_senal_a_mitad_no_rompe_el_bucle():
    caps = caps_base()
    caps["http://dc/video"] = CapFalsa(fallar_desde=10)
    pantalla = PantallaFalsa(teclas=[-1] * 80 + [TECLA_Q])
    r = VisorTresFuentes(FUENTES, pantalla, fabrica_de(caps)).ejecutar()
    assert "sin señal" in r["fuentes"]["droidcam"]["error"]
    assert r["motivo_cierre"] == "tecla q"


def test_no_se_queda_colgado_si_un_read_se_bloquea():
    caps = caps_base()
    caps["http://dc/video"] = CapFalsa(bloqueo=1.5)
    t0 = time.monotonic()
    VisorTresFuentes(
        FUENTES, PantallaFalsa(teclas=[-1] * 5 + [TECLA_Q]), fabrica_de(caps)
    ).ejecutar()
    assert time.monotonic() - t0 < 5


def test_limite_de_iteraciones():
    r = VisorTresFuentes(FUENTES, PantallaFalsa(), fabrica_de(caps_base())).ejecutar(
        max_iteraciones=5
    )
    assert r["motivo_cierre"] == "límite de iteraciones"


def test_fuentes_desde_config_usa_url_de_cv2():
    cfg = cargar_config(RUTA_EJEMPLO)
    f = {x.nombre: x for x in fuentes_desde_config(cfg)}
    assert f["local"].origen == 0 and f["local"].abrir_en_principal
    assert f["esp32"].origen == "http://192.168.43.100:80/stream"
    assert f["droidcam"].origen == "http://192.168.43.1:4747/video"


def test_script_t1_1(capsys):
    espec = importlib.util.spec_from_file_location(
        "t1_1", RAIZ / "scripts" / "t1_1_tres_fuentes.py"
    )
    mod = importlib.util.module_from_spec(espec)
    sys.modules["t1_1"] = mod
    espec.loader.exec_module(mod)
    caps = {
        0: CapFalsa(),
        "http://192.168.43.100:80/stream": CapFalsa(),
        "http://192.168.43.1:4747/video": CapFalsa(),
    }
    rc = mod.main(
        ["--config", str(RUTA_EJEMPLO)],
        pantalla=PantallaFalsa(teclas=[-1] * 10 + [TECLA_Q]),
        fabrica=fabrica_de(caps),
    )
    assert rc == 0 and "Cierre: tecla q" in capsys.readouterr().out
    assert mod.main(["--config", str(RUTA_EJEMPLO), "--fuentes", "x"]) == 2
