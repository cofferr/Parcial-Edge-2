"""Carga scripts/proteger_datos.py como módulo para probarlo."""

import importlib.util
from pathlib import Path

_ruta = Path(__file__).resolve().parent.parent / "scripts" / "proteger_datos.py"
_spec = importlib.util.spec_from_file_location("proteger_datos", _ruta)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
bloquear, bloqueada, desbloquear = _mod.bloquear, _mod.bloqueada, _mod.desbloquear
