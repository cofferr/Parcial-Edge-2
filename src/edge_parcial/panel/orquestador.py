"""Orquestador de la demo: lanza los componentes como subprocesos con cierre ordenado."""

import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from edge_parcial.config import RAIZ
from edge_parcial.panel.datos import VARIABLE_ENTORNO, VARIABLE_ORQUESTADO

log = logging.getLogger("edge_parcial.demo")

PUERTO_PANEL = 8501
GRACIA_S = 5.0  # espera tras SIGTERM antes de matar


@dataclass(frozen=True)
class Proceso:
    nombre: str
    comando: Sequence[str]
    env: dict[str, str] = field(default_factory=dict)


def _py(*args: str) -> list[str]:
    return [sys.executable, *args]


def proceso_nucleo(data_dir: Path | None = None) -> Proceso:
    """Núcleo con las tres cámaras (sin ventanas de OpenCV). Las rutas salen de la config."""
    env = {VARIABLE_ENTORNO: str(data_dir)} if data_dir else {}
    return Proceso("nucleo", _py(str(RAIZ / "scripts" / "t2_nucleo.py")), env)


def procesos_demo(
    data_dir: Path | None = None,
    puerto_panel: int = PUERTO_PANEL,
    ble: bool = True,
    rostros: bool = True,
    simular: bool = False,
    panel: bool = True,
    ganchos: Sequence[Callable[[], Proceso | None]] = (),
) -> list[Proceso]:
    """Comandos de la demo. Los ganchos permiten añadir componentes (el núcleo)."""
    env = {VARIABLE_ENTORNO: str(data_dir)} if data_dir else {}
    # El panel lanzado por la demo no debe lanzar de nuevo los componentes.
    env_panel = {**env, VARIABLE_ORQUESTADO: "1"}
    base = ["--data-dir", str(data_dir)] if data_dir else []
    estado = ["--estado", str(data_dir / "estado.json")] if data_dir else []
    lista = []
    if panel:
        lista.append(
            Proceso(
                "panel",
                _py(
                    "-m",
                    "streamlit",
                    "run",
                    str(RAIZ / "app" / "main.py"),
                    "--server.address",
                    "127.0.0.1",
                    "--server.port",
                    str(puerto_panel),
                    "--server.headless",
                    "true",
                    "--browser.gatherUsageStats",
                    "false",
                ),
                env_panel,
            )
        )
    if rostros:
        lista.append(
            Proceso("rostros", _py("-m", "edge_parcial.rostros", *estado), env)
        )
    if ble and not simular:
        csv = ["--csv", str(data_dir / "telemetria.csv")] if data_dir else []
        lista.append(Proceso("ble", _py("-m", "edge_parcial.ble", *csv, *estado), env))
    if simular:
        lista.append(
            Proceso(
                "simulador", _py(str(RAIZ / "scripts" / "simular_datos.py"), *base), env
            )
        )
    # GANCHO NÚCLEO: al unir las ramas, pasar aquí un gancho que devuelva el Proceso del
    # núcleo (ver docs/INTEGRACION.md). Un gancho puede devolver None para no lanzar nada.
    for gancho in ganchos:
        extra = gancho()
        if extra is not None:
            lista.append(extra)
    return lista


class Orquestador:
    def __init__(self, procesos: Sequence[Proceso], gracia_s: float = GRACIA_S) -> None:
        self.procesos = list(procesos)
        self.gracia_s = gracia_s
        self.hijos: dict[str, subprocess.Popen] = {}

    def lanzar(self) -> None:
        for p in self.procesos:
            log.info("Lanzando %s", p.nombre)
            self.hijos[p.nombre] = subprocess.Popen(
                list(p.comando), env={**os.environ, **p.env}
            )

    def caidos(self) -> dict[str, int]:
        """Hijos que ya terminaron, con su código de salida."""
        return {n: h.returncode for n, h in self.hijos.items() if h.poll() is not None}

    def esperar(self, critico: str = "panel", pausa_s: float = 0.5) -> None:
        """Bloquea hasta que termine el componente crítico (o todos). Ctrl+C la interrumpe."""
        avisados: set[str] = set()
        while True:
            caidos = self.caidos()
            for nombre, codigo in caidos.items():
                if nombre not in avisados:
                    avisados.add(nombre)
                    log.warning("%s terminó con código %s", nombre, codigo)
            if critico in caidos or len(caidos) == len(self.hijos):
                return
            time.sleep(pausa_s)

    def detener(self) -> None:
        """SIGTERM a todos (orden inverso al de lanzamiento) y SIGKILL a los rezagados."""
        for nombre, h in reversed(list(self.hijos.items())):
            if h.poll() is None:
                log.info("Deteniendo %s", nombre)
                h.terminate()
        limite = time.monotonic() + self.gracia_s
        for nombre, h in self.hijos.items():
            try:
                h.wait(timeout=max(0.0, limite - time.monotonic()))
            except subprocess.TimeoutExpired:
                log.warning("%s no cerró a tiempo: SIGKILL", nombre)
                h.kill()
                h.wait()
