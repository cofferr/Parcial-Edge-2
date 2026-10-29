"""Identificador de sesión: marca de tiempo del arranque de la demo.

Quien lanza la demo (el panel o scripts/demo.py) fija EDGE_SESION y los hijos la heredan, de
modo que telemetría, eventos y reconocimientos de una misma ejecución comparten `session_id`.
Un proceso lanzado por su cuenta genera la suya al primer uso.
"""

import os
from datetime import datetime

VARIABLE = "EDGE_SESION"
_propia: str | None = None


def nueva_sesion(ahora: datetime | None = None) -> str:
    return (ahora or datetime.now()).strftime("%Y%m%d-%H%M%S")


def sesion_actual() -> str:
    global _propia
    heredada = os.environ.get(VARIABLE, "").strip()
    if heredada:
        return heredada
    if _propia is None:
        _propia = nueva_sesion()
    return _propia
