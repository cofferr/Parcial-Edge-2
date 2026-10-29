"""Pruebas del orquestador con subprocesos inocuos (sin lanzar la demo real)."""

import sys
import time

from edge_parcial.panel.orquestador import Orquestador, Proceso, procesos_demo

DORMIR = [sys.executable, "-c", "import time; time.sleep(60)"]
TERCO = [
    sys.executable,
    "-c",
    "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('listo', flush=True); time.sleep(60)",
]


def test_comandos_demo_solo_loopback_y_sin_estadisticas(tmp_path):
    procs = {p.nombre: p for p in procesos_demo(tmp_path)}
    assert set(procs) == {"panel", "visor", "rostros", "ble"}
    panel = list(procs["panel"].comando)
    assert panel[panel.index("--server.address") + 1] == "127.0.0.1"
    assert panel[panel.index("--browser.gatherUsageStats") + 1] == "false"
    assert procs["panel"].env["EDGE_DATA_DIR"] == str(tmp_path)


def test_simular_sustituye_a_ble_y_ganchos():
    nucleo = Proceso("nucleo", ["true"])
    procs = procesos_demo(
        simular=True, rostros=False, ganchos=[lambda: nucleo, lambda: None]
    )
    assert [p.nombre for p in procs] == ["panel", "visor", "simulador", "nucleo"]


def test_detener_termina_a_todos():
    orq = Orquestador([Proceso("a", DORMIR), Proceso("b", DORMIR)], gracia_s=3)
    orq.lanzar()
    assert orq.caidos() == {}
    orq.detener()
    assert set(orq.caidos()) == {"a", "b"}


def test_detener_mata_al_que_ignora_sigterm():
    orq = Orquestador([Proceso("terco", TERCO)], gracia_s=0.5)
    orq.lanzar()
    time.sleep(1.0)  # que instale el manejador de la señal
    orq.detener()
    assert orq.hijos["terco"].poll() is not None


def test_esperar_vuelve_cuando_cae_el_critico():
    orq = Orquestador(
        [Proceso("panel", [sys.executable, "-c", "pass"]), Proceso("b", DORMIR)],
        gracia_s=3,
    )
    orq.lanzar()
    orq.esperar(pausa_s=0.05)
    assert "panel" in orq.caidos()
    orq.detener()
