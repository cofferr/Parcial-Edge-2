"""Cuadro con el nombre sobre las fotos (portado de la app original)."""

import time
from datetime import datetime

import cv2
import numpy as np

from edge_parcial.ble import gateway as modulo_gateway
from edge_parcial.ble.gateway import Gateway, ParamsBle
from edge_parcial.ble.telemetria import EscritorTelemetria
from edge_parcial.nucleo.reconocimiento import DespachadorRostros
from edge_parcial.panel.consultas import capturas_pir
from edge_parcial.panel.datos import Rutas
from edge_parcial.rostros.anotar import anotar_jpeg, dibujar_caras

CAJA = {"top": 40, "right": 140, "bottom": 140, "left": 40}


def _jpeg(alto=240, ancho=320) -> bytes:
    ok, buf = cv2.imencode(".jpg", np.full((alto, ancho, 3), 100, np.uint8))
    assert ok
    return buf.tobytes()


def test_conocido_verde_y_desconocido_rojo():
    base = np.full((240, 320, 3), 100, np.uint8)
    verde = dibujar_caras(base, [{"identidad": "Ana", "caja": CAJA}])
    rojo = dibujar_caras(base, [{"identidad": "desconocido", "caja": CAJA}])
    assert tuple(verde[40, 90]) == (0, 255, 0)  # borde superior del cuadro
    assert tuple(rojo[40, 90]) == (0, 0, 255)
    assert (base == 100).all()  # la imagen original no se modifica
    assert not np.array_equal(
        verde[120:140, 40:140], base[120:140, 40:140]
    )  # etiqueta con texto


def test_anotar_jpeg_devuelve_un_jpeg_y_none_si_no_se_puede_leer():
    out = anotar_jpeg(_jpeg(), [{"identidad": "Ana", "caja": CAJA}])
    assert out[:2] == b"\xff\xd8" and out != _jpeg()
    assert anotar_jpeg(b"no es jpeg", [{"identidad": "Ana", "caja": CAJA}]) is None


def test_la_foto_del_quorum_lleva_el_cuadro_y_el_original_se_conserva(tmp_path):
    jpeg = _jpeg()
    d = DespachadorRostros(
        lambda f, e: jpeg,
        tmp_path / "s",
        tmp_path / "r.csv",
        print,
        lambda j, f: [{"identidad": "Ana", "distancia": 0.3, "caja": CAJA}],
    )
    d.disparar(1, ["esp32"])
    d.esperar()
    fotos = sorted(p.name for p in (tmp_path / "s").iterdir())
    anotada = next(n for n in fotos if not n.endswith("_sin_anotar.jpg"))
    assert any(n.endswith("_sin_anotar.jpg") for n in fotos)
    assert (tmp_path / "s" / anotada).read_bytes() != jpeg  # tiene el cuadro
    sin = next(n for n in fotos if n.endswith("_sin_anotar.jpg"))
    assert (tmp_path / "s" / sin).read_bytes() == jpeg  # evidencia original intacta


def test_la_captura_del_pir_se_reconoce_en_un_hilo(tmp_path, monkeypatch):
    jpeg = _jpeg()
    monkeypatch.setattr(modulo_gateway, "obtener_ultimo", lambda f, e: jpeg)
    params = ParamsBle(fuente_foto="esp32", carpeta_fotos=tmp_path / "s")
    gw = Gateway(
        None,
        EscritorTelemetria(tmp_path / "t.csv"),
        tmp_path / "e.json",
        params,
        lambda: datetime(2026, 10, 28, 19, 0, 0).astimezone(),
        lambda j, f: [{"identidad": "Luis", "distancia": 0.4, "caja": CAJA}],
    )
    gw.al_recibir(bytes.fromhex("9c 09 7a 17 ff ff 01"))
    for _ in range(50):
        if (tmp_path / "s" / "pir_esp32_20261028_190000_reconocido.jpg").exists():
            break
        time.sleep(0.05)
    assert (
        tmp_path / "s" / "pir_esp32_20261028_190000.jpg"
    ).read_bytes() == jpeg  # original
    reconocida = (
        tmp_path / "s" / "pir_esp32_20261028_190000_reconocido.jpg"
    ).read_bytes()
    assert reconocida != jpeg


def test_servicio_caido_anota_error_y_deja_la_captura_original(tmp_path, monkeypatch):
    monkeypatch.setattr(modulo_gateway, "obtener_ultimo", lambda f, e: _jpeg())

    def caido(j, f):
        raise ConnectionRefusedError("nadie")

    gw = Gateway(
        None,
        EscritorTelemetria(tmp_path / "t.csv"),
        tmp_path / "e.json",
        ParamsBle(fuente_foto="esp32", carpeta_fotos=tmp_path / "s"),
        lambda: datetime(2026, 10, 28, 19, 0, 0).astimezone(),
        caido,
    )
    gw.al_recibir(bytes.fromhex("9c 09 7a 17 ff ff 01"))
    for _ in range(50):
        if any("Reconocimiento de la captura" in e for e in gw.errores):
            break
        time.sleep(0.05)
    assert any("Reconocimiento de la captura" in e for e in gw.errores)
    assert [p.name for p in (tmp_path / "s").iterdir()] == [
        "pir_esp32_20261028_190000.jpg"
    ]


def test_el_panel_prefiere_la_captura_reconocida(tmp_path):
    r = Rutas(base=tmp_path, snapshots=tmp_path / "s")
    r.snapshots.mkdir()
    (r.snapshots / "pir_esp32_20261028_190000.jpg").write_bytes(_jpeg())
    (r.base / "telemetria.csv").write_text(
        "timestamp,temperatura_c,humedad_pct,suelo_adc,movimiento,foto,trama_hex,session_id\n"
        "2026-10-28T19:00:00-05:00,24,60,,1,pir_esp32_20261028_190000.jpg,aa,S\n"
    )
    assert capturas_pir(r)[0].ruta.name == "pir_esp32_20261028_190000.jpg"
    (r.snapshots / "pir_esp32_20261028_190000_reconocido.jpg").write_bytes(_jpeg())
    assert capturas_pir(r)[0].ruta.name == "pir_esp32_20261028_190000_reconocido.jpg"
