"""Arranque unificado: el panel lanza los componentes una sola vez por servidor Streamlit.

- Un candado de archivo (`flock`) en la carpeta de datos garantiza un único dueño: una segunda
  pestaña o un segundo servidor ve el candado ocupado y no lanza nada. El sistema operativo
  suelta el candado aunque el servidor muera a la fuerza.
- `pids.json` guarda los hijos lanzados; si el servidor anterior murió sin cerrarlos, el
  siguiente los termina antes de lanzar los suyos (sin huérfanos).
- Al cerrar el servidor (`atexit`) se detienen con SIGTERM y, a los 5 s, SIGKILL.
- Un hijo caído se informa pero no se relanza solo; `reiniciar()` los relanza todos.
"""

import atexit
import fcntl
import json
import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from edge_parcial.panel.datos import (
    VARIABLE_ENTORNO,
    VARIABLE_ORQUESTADO,
    rutas_por_defecto,
)
from edge_parcial.panel.orquestador import Orquestador, proceso_nucleo, procesos_demo
from edge_parcial.panel.respaldo import respaldar
from edge_parcial.rostros.reconocedor import CARPETA_ROSTROS
from edge_parcial.sesion import nueva_sesion

log = logging.getLogger("edge_parcial.panel")

# Componente del estado.json que cubre cada proceso hijo.
COMPONENTE_DE = {"ble": "ble", "rostros": "servicio_rostros", "nucleo": "nucleo"}
PROCESOS_PROPIOS = ("edge_parcial", "t2_nucleo", "simular_datos")


@dataclass(frozen=True)
class Opciones:
    simular: bool = False
    sin_ble: bool = False
    sin_rostros: bool = False
    sin_nucleo: bool = False

    @classmethod
    def de_entorno(cls) -> Opciones:
        def activa(nombre: str) -> bool:
            return os.environ.get(nombre, "").strip().lower() in (
                "1",
                "true",
                "si",
                "sí",
            )

        return cls(
            activa("EDGE_SIMULAR"),
            activa("EDGE_SIN_BLE"),
            activa("EDGE_SIN_ROSTROS"),
            activa("EDGE_SIN_NUCLEO"),
        )


def orquestado_externamente() -> bool:
    return os.environ.get(VARIABLE_ORQUESTADO) == "1"


def _vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _es_nuestro(pid: int) -> bool:
    """Evita matar a un proceso ajeno que reutilizó el pid."""
    salida = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    ).stdout
    return (
        "edge_parcial" in salida or "t2_nucleo" in salida or "simular_datos" in salida
    )


class Arranque:
    def __init__(self, base: Path, gracia_s: float = 5.0) -> None:
        self.base = Path(base)
        self.gracia_s = gracia_s
        self.base.mkdir(parents=True, exist_ok=True)
        self._ruta_candado = self.base / ".panel.lock"
        self._ruta_pids = self.base / ".panel.pids.json"
        self._candado = None
        self.dueno = False
        self.orq: Orquestador | None = None
        self.opciones = Opciones()
        self.sesion = nueva_sesion()  # session_id de esta ejecución de la demo
        self.respaldo: Path | None = None
        self._mutex = threading.Lock()
        atexit.register(self.detener)

    # -- candado y huérfanos --------------------------------------------------

    def _tomar_candado(self) -> bool:
        if self._candado is not None:
            return True
        f = open(self._ruta_candado, "w")  # noqa: SIM115 - vive mientras viva el servidor
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._candado = f
        return True

    def _matar_huerfanos(self) -> None:
        try:
            pids = json.loads(self._ruta_pids.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return
        for nombre, pid in pids.items():
            if isinstance(pid, int) and _vivo(pid) and _es_nuestro(pid):
                log.warning("Terminando %s huérfano (pid %s)", nombre, pid)
                os.kill(pid, signal.SIGTERM)
        limite = time.monotonic() + self.gracia_s
        for pid in pids.values():
            while isinstance(pid, int) and _vivo(pid) and time.monotonic() < limite:
                time.sleep(0.1)
            if isinstance(pid, int) and _vivo(pid) and _es_nuestro(pid):
                os.kill(pid, signal.SIGKILL)
        self._ruta_pids.unlink(missing_ok=True)

    def _respaldar(self) -> None:
        """Copia de seguridad previa al arranque (solo copia; un fallo no impide arrancar)."""
        try:
            self.respaldo = respaldar(self.base, CARPETA_ROSTROS)
        except OSError as e:
            log.warning("No se pudo hacer el respaldo: %s", e)

    # -- ciclo de vida ----------------------------------------------------------

    def _construir(self, o: Opciones) -> Orquestador:
        data_dir = (
            Path(os.environ[VARIABLE_ENTORNO])
            if VARIABLE_ENTORNO in os.environ
            else None
        )
        procesos = procesos_demo(
            data_dir,
            ble=not o.sin_ble,
            rostros=not o.sin_rostros,
            simular=o.simular,
            panel=False,
            ganchos=[]
            if (o.sin_nucleo or o.simular)
            else [lambda: proceso_nucleo(data_dir)],
        )
        return Orquestador(procesos, gracia_s=self.gracia_s)

    def iniciar(self, opciones: Opciones | None = None) -> bool:
        """Lanza los componentes si este servidor es el dueño. False = otro servidor lo es."""
        with self._mutex:
            if self.orq is not None:
                return True
            if not self._tomar_candado():
                return False
            self.dueno = True
            self.opciones = opciones or Opciones.de_entorno()
            self._matar_huerfanos()
            self._respaldar()
            self.orq = self._construir(self.opciones)
            self.orq.lanzar()
            self._ruta_pids.write_text(
                json.dumps({n: h.pid for n, h in self.orq.hijos.items()}),
                encoding="utf-8",
            )
            return True

    def detener(self) -> None:
        with self._mutex:
            if self.orq is not None:
                self.orq.detener()
                self.orq = None
            if self.dueno:
                self._ruta_pids.unlink(missing_ok=True)

    def reiniciar(self, opciones: Opciones | None = None) -> bool:
        if not self.dueno:
            return False
        self.detener()
        self.dueno = (
            False  # iniciar() vuelve a marcarlo; el candado sigue en nuestras manos
        )
        return self.iniciar(opciones or self.opciones)

    def caidos(self) -> dict[str, int]:
        """Hijos que terminaron, con su código de salida (vacío si no somos el dueño)."""
        return self.orq.caidos() if self.orq is not None else {}


_instancia: Arranque | None = None


def obtener() -> Arranque:
    """Una instancia por proceso del servidor (el módulo persiste entre reruns y sesiones)."""
    global _instancia
    if _instancia is None:
        _instancia = Arranque(rutas_por_defecto().base)
    return _instancia
