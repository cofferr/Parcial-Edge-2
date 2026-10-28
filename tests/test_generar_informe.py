"""Generador del borrador del informe: formato, marcadores y trazabilidad."""

import importlib.util
import re
import sys

import pytest

from edge_parcial.config import RAIZ

sys.path.insert(0, str(RAIZ / "scripts"))
spec = importlib.util.spec_from_file_location(
    "generar_informe", RAIZ / "scripts" / "generar_informe.py"
)
gi = importlib.util.module_from_spec(spec)
sys.modules["generar_informe"] = gi
spec.loader.exec_module(gi)


def test_fmt_redondea_solo_al_presentar():
    assert gi.fmt("0.7428571428571429") == "0.743"
    assert gi.fmt("300.0") == "300"
    assert gi.fmt("") == gi.SIN_DATO
    assert gi.fmt("2.670039999999596e-07") == "2.670e-07"
    assert gi.fmt("True") == "sí"


def test_v_exige_una_sola_fila(monkeypatch):
    monkeypatch.setattr(
        gi, "filas", lambda rel: [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}]
    )
    assert gi.v("x.csv", "b", a="2") == "y"
    with pytest.raises(ValueError, match="0 filas"):
        gi.v("x.csv", "b", a="9")


@pytest.mark.skipif(
    not (RAIZ / "data" / "processed" / "t2_3_resumen.csv").is_file(),
    reason="sin datos procesados locales",
)
def test_generar_borrador_completo():
    doc = gi.generar()
    for tarea in (
        "1.1",
        "1.2",
        "1.3",
        "1.4",
        "1.5",
        "1.6",
        "2.1",
        "2.2",
        "2.3",
        "2.4",
        "2.5",
        "3.1",
        "3.2",
        "3.3",
    ):
        assert f"## Tarea {tarea}:" in doc
    for seccion in (
        "Fórmulas aplicadas",
        "Limitaciones del experimento",
        "Decisiones y desviaciones",
        "Cobertura del enunciado",
        "Archivos para subir a Overleaf",
    ):
        assert f"## {seccion}" in doc
    assert gi.PEND in doc and gi.CITA in doc
    assert "pese al resultado" in doc  # nota de la fase C
    assert not re.search(r"\b(nan|None)\b", doc)
