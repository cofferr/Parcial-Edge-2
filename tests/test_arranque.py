"""Arranque unificado, visor de cámaras y filas de conexión (sin lanzar la demo real)."""

import json
import os
import sys
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from edge_parcial.panel import arranque
from edge_parcial.panel.arranque import Arranque, Opciones
from edge_parcial.panel.consultas import estado_por_fuente
from edge_parcial.panel.datos import Rutas
from edge_parcial.panel.orquestador import Orquestador, Proceso
from edge_parcial.panel.simulador import Simulador

DORMIR = [sys.executable, "-c", "import time; time.sleep(60)"]
SALIR = [sys.executable, "-c", "raise SystemExit(3)"]
APP = str(Path(__file__).resolve().parent.parent / "app" / "main.py")


def _falso(monkeypatch, procesos):
    monkeypatch.setattr(
        Arranque,
        "_construir",
        lambda self, o: Orquestador(procesos, gracia_s=self.gracia_s),
    )


def _vivo(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_lanza_una_sola_vez_y_el_segundo_servidor_no_duplica(tmp_path, monkeypatch):
    _falso(monkeypatch, [Proceso("a", DORMIR)])
    uno, dos = Arranque(tmp_path, gracia_s=2), Arranque(tmp_path, gracia_s=2)
    assert uno.iniciar() and uno.iniciar()  # idempotente
    pid = uno.orq.hijos["a"].pid
    assert dos.iniciar() is False and dos.orq is None  # candado ocupado
    assert uno.orq.hijos["a"].pid == pid
    uno.detener()
    assert not _vivo(pid)


def test_hijo_caido_se_informa_y_no_se_relanza(tmp_path, monkeypatch):
    _falso(monkeypatch, [Proceso("ble", SALIR), Proceso("b", DORMIR)])
    a = Arranque(tmp_path, gracia_s=2)
    a.iniciar()
    time.sleep(1.0)
    assert a.caidos() == {"ble": 3}
    a.detener()


def test_reiniciar_relanza_todos(tmp_path, monkeypatch):
    _falso(monkeypatch, [Proceso("ble", SALIR), Proceso("b", DORMIR)])
    a = Arranque(tmp_path, gracia_s=2)
    a.iniciar()
    viejo = a.orq.hijos["b"].pid
    assert a.reiniciar(Opciones(simular=True)) and a.opciones.simular
    assert a.orq.hijos["b"].pid != viejo and not _vivo(viejo)
    a.detener()


def test_termina_huerfanos_de_un_servidor_muerto(tmp_path, monkeypatch):
    # Un hijo huérfano cuyo comando menciona edge_parcial (así lo reconoce como suyo).
    cmd = [sys.executable, "-c", "import time; time.sleep(60)  # edge_parcial"]
    huerfano = Orquestador([Proceso("h", cmd)], gracia_s=2)
    huerfano.lanzar()
    pid = huerfano.hijos["h"].pid
    (tmp_path / ".panel.pids.json").write_text(json.dumps({"h": pid}))
    _falso(monkeypatch, [Proceso("a", DORMIR)])
    a = Arranque(tmp_path, gracia_s=2)
    a.iniciar()
    assert huerfano.hijos["h"].wait(timeout=5) is not None
    a.detener()


def test_opciones_desde_entorno(monkeypatch):
    monkeypatch.setenv("EDGE_SIMULAR", "1")
    monkeypatch.setenv("EDGE_SIN_ROSTROS", "true")
    assert Opciones.de_entorno() == Opciones(simular=True, sin_rostros=True)


def test_orquestado_externamente(monkeypatch):
    monkeypatch.setenv("EDGE_ORQUESTADO", "1")
    assert arranque.orquestado_externamente()


@pytest.fixture
def rutas(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EDGE_ORQUESTADO", "1")
    return Rutas(base=tmp_path, snapshots=tmp_path / "snapshots")


def test_estado_por_fuente_traduce_banderas(rutas):
    (rutas.base / "eventos.csv").write_text(
        "run_id,ts_wall,ventana,t_ventana_ini_ns,voto_esp32,voto_droidcam,voto_local,"
        "bandera_esp32,bandera_droidcam,bandera_local,Q,n_true,alerta\n"
        "r,t,1,0,1,0,0,movimiento,tapada,sin_datos,0.3,1,0\n"
    )
    estados, alerta = estado_por_fuente(rutas)
    assert [estados[f].estado for f in ("esp32", "droidcam", "local")] == [
        "movimiento",
        "tapada",
        "sin_datos",
    ]
    assert estados["esp32"].voto is True and alerta is False


def test_camaras_con_simulacion_muestra_las_tres(rutas):
    sim = Simulador(rutas, semilla=3)
    for _ in range(5):
        sim.paso()
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception


def test_camaras_incrusta_los_tres_streams(rutas):
    at = AppTest.from_file(
        str(Path(APP).parent / "paginas" / "camaras.py"), default_timeout=30
    ).run()
    assert not at.exception, at.exception
    html = " ".join(str(e.value) for e in at.get("html"))
    for f in ("esp32", "droidcam", "local"):
        assert f"http://127.0.0.1:8766/stream/{f}" in html


def test_camaras_una_sola(rutas):
    at = AppTest.from_file(
        str(Path(APP).parent / "paginas" / "camaras.py"), default_timeout=30
    ).run()
    at.radio[0].set_value("Una cámara").run()
    html = " ".join(str(e.value) for e in at.get("html"))
    assert html.count("/stream/") == 1


def test_barra_marca_seis_componentes_con_semaforo(rutas):
    sim = Simulador(rutas, semilla=3)
    sim.paso()
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception, at.exception
    lateral = " ".join(m.value for m in at.sidebar.markdown)
    for etiqueta in ("BLE", "Núcleo", "ESP32-CAM", "DroidCam", "Cámara local"):
        assert etiqueta in lateral
    assert lateral.count("🟢") == 7  # seis componentes + el estado del quórum
