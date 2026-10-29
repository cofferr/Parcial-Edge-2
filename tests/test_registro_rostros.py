"""Registro de rostros: validación (exactamente uno), muestras, borrado y recarga en caliente."""

from pathlib import Path

import cv2
import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

from edge_parcial.rostros import registro
from edge_parcial.rostros.reconocedor import ReconocedorDlib
from edge_parcial.rostros.registro import ErrorRegistro, agregar_muestra, borrar, listar

PAGINA = str(Path(__file__).resolve().parent.parent / "app" / "paginas" / "registro.py")


def _jpeg(v=120) -> bytes:
    ok, buf = cv2.imencode(".jpg", np.full((40, 40, 3), v, np.uint8))
    assert ok
    return buf.tobytes()


def test_rechaza_cero_o_varios_rostros_y_nombres_peligrosos(tmp_path):
    with pytest.raises(ErrorRegistro, match="ningún rostro"):
        agregar_muestra("Ana", _jpeg(), tmp_path, contar=lambda _: 0)
    with pytest.raises(ErrorRegistro, match="2 rostros"):
        agregar_muestra("Ana", _jpeg(), tmp_path, contar=lambda _: 2)
    for malo in ("", "../x", "a/b", ".oculto", "x" * 41):
        with pytest.raises(ErrorRegistro, match="Nombre no válido"):
            agregar_muestra(malo, _jpeg(), tmp_path, contar=lambda _: 1)
    with pytest.raises(ErrorRegistro, match="no se pudo leer"):
        agregar_muestra("Ana", b"no es imagen", tmp_path, contar=lambda _: 1)
    assert listar(tmp_path) == {}  # nada se guardó


def test_varias_muestras_por_persona_listar_y_borrar(tmp_path):
    for _ in range(3):
        agregar_muestra("Ana María", _jpeg(), tmp_path, contar=lambda _: 1)
    agregar_muestra("Luis", _jpeg(), tmp_path, contar=lambda _: 1)
    (tmp_path / "Pedro.jpg").write_bytes(_jpeg())  # formato de la app original
    assert listar(tmp_path) == {"Ana María": 3, "Luis": 1, "Pedro": 1}
    assert borrar("Ana María", tmp_path) == 3 and borrar("Pedro", tmp_path) == 1
    assert listar(tmp_path) == {"Luis": 1}


def test_reconocedor_recarga_sin_reiniciar(tmp_path, monkeypatch):
    class FR:  # face_recognition mínimo: cada imagen "tiene" un rostro con encoding fijo
        @staticmethod
        def load_image_file(ruta):
            return np.zeros((8, 8, 3), np.uint8)

        @staticmethod
        def face_encodings(imagen, *a):
            return [np.zeros(128)]

    monkeypatch.setitem(__import__("sys").modules, "face_recognition", FR)
    rec = ReconocedorDlib(tmp_path)
    assert rec.nombres == [] and rec.recargar_si_cambio() is False
    agregar_muestra("Ana", _jpeg(), tmp_path, contar=lambda _: 1)
    agregar_muestra("Ana", _jpeg(), tmp_path, contar=lambda _: 1)
    assert rec.recargar_si_cambio() is True and rec.nombres == ["Ana", "Ana"]
    borrar("Ana", tmp_path)
    assert rec.recargar_si_cambio() is True and rec.nombres == []


def test_pagina_registro_sin_personas_y_con_nombre_invalido(monkeypatch, tmp_path):
    monkeypatch.setattr(registro, "CARPETA_ROSTROS", tmp_path)
    monkeypatch.setattr(registro, "listar", lambda carpeta=tmp_path: {})
    at = AppTest.from_file(PAGINA, default_timeout=30).run()
    assert not at.exception, at.exception
    assert any("Todavía no hay personas" in i.value for i in at.info)
    html = " ".join(str(e.value) for e in at.get("html"))
    assert "/stream/local" in html
