"""Pruebas del servicio de rostros (reconocedor falso; dlib solo sin rostros)."""

import inspect

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from edge_parcial.panel.estado import leer_estado
from edge_parcial.rostros import __main__ as principal
from edge_parcial.rostros.reconocedor import (
    DESCONOCIDO,
    Deteccion,
    ReconocedorDlib,
    ReconocedorFalso,
    crear_reconocedor,
)
from edge_parcial.rostros.servicio import HOST, crear_app


def jpeg(ancho=320, alto=240) -> bytes:
    img = np.full((alto, ancho, 3), 127, np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def test_respuesta_con_caras_y_cajas_en_pixeles_originales():
    falso = ReconocedorFalso([Deteccion("Ana", 0.31, (10, 50, 40, 20))])
    cli = TestClient(crear_app(falso, {"local": 0.25}))
    r = cli.post("/reconocer?fuente=local", content=jpeg(640, 480))
    assert r.status_code == 200
    cuerpo = r.json()
    assert falso.ultima_forma == (120, 160, 3)  # 640x480 * 0,25
    assert cuerpo["caras"] == [
        {
            "identidad": "Ana",
            "distancia": 0.31,
            "caja": {"top": 40, "right": 200, "bottom": 160, "left": 80},
        }
    ]


def test_factor_por_fuente():
    falso = ReconocedorFalso()
    cli = TestClient(crear_app(falso))
    cli.post("/reconocer?fuente=esp32", content=jpeg(320, 240))
    assert falso.ultima_forma == (240, 320, 3)  # la ESP32 no se reduce
    cli.post("/reconocer?fuente=droidcam", content=jpeg(1280, 720))
    assert falso.ultima_forma == (360, 640, 3)


def test_sin_caras_y_desconocido():
    falso = ReconocedorFalso([Deteccion(DESCONOCIDO, None, (0, 1, 1, 0))])
    cli = TestClient(crear_app(falso))
    assert (
        cli.post("/reconocer?fuente=esp32", content=jpeg()).json()["caras"][0][
            "distancia"
        ]
        is None
    )
    assert (
        TestClient(crear_app(ReconocedorFalso()))
        .post("/reconocer?fuente=esp32", content=jpeg())
        .json()["caras"]
        == []
    )


def test_jpeg_invalido_y_fuente_obligatoria():
    cli = TestClient(crear_app(ReconocedorFalso()))
    assert cli.post("/reconocer?fuente=esp32", content=b"no es jpeg").status_code == 400
    assert cli.post("/reconocer", content=jpeg()).status_code == 422
    assert cli.get("/salud").json()["reconocedor"] == "falso"


def test_factor_invalido():
    with pytest.raises(ValueError):
        crear_app(ReconocedorFalso(), {"esp32": 0})


def test_latido_en_estado_json(tmp_path):
    ruta = tmp_path / "estado.json"
    with TestClient(crear_app(ReconocedorFalso(), ruta_estado=ruta)) as cli:
        cli.post("/reconocer?fuente=esp32", content=jpeg())
    assert leer_estado(ruta)["servicio_rostros"]["vivo"] is True


def test_solo_loopback():
    assert HOST == "127.0.0.1"
    assert "--host" not in inspect.getsource(
        principal
    )  # el anfitrión no es configurable


def test_dlib_sin_rostros_y_carpeta_vacia(tmp_path):
    rec = ReconocedorDlib(tmp_path / "rostros_conocidos")
    assert rec.nombres == []
    assert rec.reconocer(np.full((120, 160, 3), 127, np.uint8)) == []


def test_crear_reconocedor_falso_forzado(tmp_path):
    assert crear_reconocedor(tmp_path, forzar_falso=True).nombre == "falso"
