"""Pruebas de la base del proyecto (Paso 0)."""

import tomllib
from pathlib import Path

import edge_parcial
import edge_parcial.acquisition
import edge_parcial.analysis

RAIZ = Path(__file__).resolve().parent.parent


def test_paquete_importa():
    assert callable(edge_parcial.main)
    assert edge_parcial.acquisition and edge_parcial.analysis


def test_carpetas_clave_existen():
    for ruta in [
        "src/edge_parcial/acquisition",
        "src/edge_parcial/analysis",
        "scripts",
        "data/raw",
        "data/processed",
        "data/recordings",
        "docs",
        "tests",
        "firmware/esp32cam",
    ]:
        assert (RAIZ / ruta).is_dir(), ruta


def test_config_ejemplo_carga():
    with open(RAIZ / "config" / "config.example.toml", "rb") as f:
        cfg = tomllib.load(f)
    for seccion in ["red", "esp32", "droidcam", "local", "propagacion"]:
        assert seccion in cfg
    assert cfg["esp32"]["velocidad_nominal_fuente"]


def test_documentos_existen():
    for doc in ["docs/DISENO.md", "docs/matriz_formulas.md", "CLAUDE.md"]:
        assert (RAIZ / doc).is_file(), doc
    assert (RAIZ / "firmware/esp32cam/secrets.example.h").is_file()


def test_gitignore_cubre_archivos_sensibles():
    texto = (RAIZ / ".gitignore").read_text()
    for patron in [
        "config/config.toml",
        "data/recordings",
        "secrets.h",
        ".venv",
        "/c.jpg",
        "/s.bin",
        "/*.jpg",
        "/*.bin",
    ]:
        assert patron in texto, patron
