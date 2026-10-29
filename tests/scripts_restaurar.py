"""Carga scripts/restaurar_respaldo.py como módulo para probarlo."""

import importlib.util
from pathlib import Path

_ruta = Path(__file__).resolve().parent.parent / "scripts" / "restaurar_respaldo.py"
_spec = importlib.util.spec_from_file_location("restaurar_respaldo", _ruta)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
restaurar = _mod.restaurar
