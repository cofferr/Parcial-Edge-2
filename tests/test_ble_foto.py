"""Foto por movimiento del gateway BLE."""

import asyncio
from datetime import datetime

from edge_parcial.ble import foto as modulo_foto
from edge_parcial.ble.gateway import Gateway, ParamsBle
from edge_parcial.ble.telemetria import EscritorTelemetria


def _trama(mov: int) -> bytes:
    return bytes.fromhex("9c 09 7a 17 ff ff") + bytes([mov])


def test_movimiento_guarda_foto_y_nombre(tmp_path, monkeypatch):
    monkeypatch.setattr(modulo_foto, "extraer_frame", lambda url, timeout=15: b"JPG")
    params = ParamsBle(url_foto="http://x/video", carpeta_fotos=tmp_path / "s")
    reloj = lambda: datetime(2026, 10, 28, 19, 0, 0).astimezone()

    async def prueba():
        gw = Gateway(
            None,
            EscritorTelemetria(tmp_path / "t.csv"),
            tmp_path / "e.json",
            params,
            reloj,
        )
        gw.al_recibir(_trama(1))
        gw.al_recibir(_trama(0))
        await asyncio.sleep(0.2)

    asyncio.run(prueba())
    filas = (tmp_path / "t.csv").read_text().splitlines()
    assert "foto_20261028_190000.jpg" in filas[1]
    assert ",," in filas[2] or "0,,9c" in filas[2]
    assert (tmp_path / "s" / "foto_20261028_190000.jpg").read_bytes() == b"JPG"
