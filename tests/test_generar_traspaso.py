"""Generador del documento de traspaso: secciones y tablas sin redondear."""

import importlib.util
import sys

import pytest

from edge_parcial.config import RAIZ

ruta = RAIZ / "scripts" / "generar_traspaso.py"
spec = importlib.util.spec_from_file_location("generar_traspaso", ruta)
gt = importlib.util.module_from_spec(spec)
sys.modules["generar_traspaso"] = gt
spec.loader.exec_module(gt)


def test_seccion_md_corta_en_la_siguiente_seccion():
    texto = "## 3. Uno\ncuerpo\n## 4. Dos\notro\n"
    assert gt.seccion_md(texto, "3\\.") == "## 3. Uno\ncuerpo\n"
    assert "No se encontró" in gt.seccion_md(texto, "9\\.")


def test_config_enmascara_las_ip():
    texto = gt.config_enmascarada()
    assert "192.168" not in texto
    assert '"<oculta>"' in texto
    assert "velocidad_nominal_fuente" in texto  # las citas se conservan


def test_tabla_md_copia_el_texto_sin_redondear(tmp_path, monkeypatch):
    (tmp_path / "t.csv").write_text("a,b\n0.7428571428571429,x|y\n")
    monkeypatch.setattr(gt, "RAIZ", tmp_path)
    md = gt.tabla_md(gt.Path("t.csv"))
    assert "0.7428571428571429" in md
    assert "x\\|y" in md
    assert "Falta" in gt.tabla_md(gt.Path("no_existe.csv"))


def test_nota_de_la_fase_c_cita_la_evidencia():
    assert "pese al resultado" in gt.NOTA_FASE_C
    assert "nunca" in gt.NOTA_FASE_C
    assert "37 ventanas" in gt.NOTA_FASE_C


@pytest.mark.skipif(
    not (RAIZ / "data" / "processed" / "t2_3_resumen.csv").is_file(),
    reason="sin datos procesados locales",
)
def test_generar_incluye_todas_las_tareas():
    doc = gt.generar()
    for t in gt.TAREAS:
        assert t["titulo"] in doc
    assert "Falta `" not in doc
