"""Pruebas del módulo BLE con un cliente simulado (sin hardware)."""

import asyncio
import csv
import json
import struct
from datetime import UTC, datetime

import pytest

from edge_parcial.ble.gateway import Gateway, ParamsBle
from edge_parcial.ble.telemetria import COLUMNAS, EscritorTelemetria
from edge_parcial.ble.trama import Lectura, TramaInvalida, decodificar
from edge_parcial.panel.estado import actualizar_componente, leer_estado

TRAMA = struct.pack("<hHHB", 2280, 5780, 0xFFFF, 0)


def test_decodificar_suelo_sin_sensor():
    assert decodificar(TRAMA) == Lectura(22.8, 57.8, None, 0)


def test_decodificar_con_suelo_y_temperatura_negativa():
    assert decodificar(struct.pack("<hHHB", -550, 1000, 1234, 1)) == Lectura(
        -5.5, 10.0, 1234, 1
    )


def test_trama_de_longitud_incorrecta():
    with pytest.raises(TramaInvalida):
        decodificar(b"\x00" * 6)


def test_escritor_cabecera_una_sola_vez(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_SESION", "S1")
    ruta = tmp_path / "t.csv"
    ts = datetime(2026, 10, 28, 14, 0, tzinfo=UTC)
    for _ in range(2):
        EscritorTelemetria(ruta).agregar(ts, decodificar(TRAMA), TRAMA)
    filas = list(csv.reader(ruta.open()))
    assert filas[0] == COLUMNAS
    assert len(filas) == 3
    assert filas[1][:-1] == [
        "2026-10-28T14:00:00+00:00",
        "22.80",
        "57.80",
        "",
        "0",
        "",
        "e8 08 94 16 ff ff 00",
    ]
    assert filas[1][-1] == "S1"  # session_id


class FuenteFalsa:
    """Cada sesión: lista de tramas; `None` en la lista = error de conexión."""

    def __init__(self, sesiones):
        self.sesiones = list(sesiones)
        self.intentos = 0

    async def sesion(self, al_recibir, al_conectar):
        self.intentos += 1
        if not self.sesiones:
            await asyncio.Event().wait()  # quieta hasta que la cancelen
        tramas = self.sesiones.pop(0)
        if tramas is None:
            raise ConnectionError("no encontrado")
        al_conectar()
        for t in tramas:
            al_recibir(t)
            await asyncio.sleep(0)


PARAMS = ParamsBle(backoff_inicial_s=0.01, backoff_max_s=0.04, latido_s=0.01)


async def _correr(gw, hasta):
    tarea = asyncio.create_task(gw.ejecutar())
    for _ in range(300):
        await asyncio.sleep(0.01)
        if hasta():
            break
    gw.detener()
    await asyncio.wait_for(tarea, 2)


def test_reconecta_y_escribe(tmp_path):
    fuente = FuenteFalsa([None, [TRAMA, b"\x01\x02", TRAMA], [TRAMA]])
    gw = Gateway(
        fuente, EscritorTelemetria(tmp_path / "t.csv"), tmp_path / "e.json", PARAMS
    )
    asyncio.run(_correr(gw, lambda: gw.lecturas >= 3 and fuente.intentos >= 4))
    assert gw.lecturas == 3
    assert len(list(csv.reader((tmp_path / "t.csv").open()))) == 4  # cabecera + 3
    assert any("Trama de 2 bytes" in e for e in gw.errores)
    estado = json.loads((tmp_path / "e.json").read_text())["ble"]
    assert estado["vivo"] is False  # tras detener
    assert estado["ultima_marca"]


def test_backoff_acotado(tmp_path):
    fuente = FuenteFalsa([None] * 6)
    gw = Gateway(
        fuente, EscritorTelemetria(tmp_path / "t.csv"), tmp_path / "e.json", PARAMS
    )
    esperas = []
    original = gw._esperar

    async def espiar(s):
        esperas.append(s)
        await original(s)

    gw._esperar = espiar
    asyncio.run(_correr(gw, lambda: len(esperas) >= 5))
    assert esperas[:4] == [0.01, 0.02, 0.04, 0.04]


def test_latido_vivo_mientras_conectado(tmp_path):
    class Larga(FuenteFalsa):
        async def sesion(self, al_recibir, al_conectar):
            al_conectar()
            al_recibir(TRAMA)
            await asyncio.Event().wait()

    gw = Gateway(
        Larga([]), EscritorTelemetria(tmp_path / "t.csv"), tmp_path / "e.json", PARAMS
    )
    asyncio.run(
        _correr(gw, lambda: leer_estado(tmp_path / "e.json").get("ble", {}).get("vivo"))
    )
    assert gw.lecturas == 1


def test_actualizar_componente_no_pisa_otros(tmp_path):
    ruta = tmp_path / "e.json"
    actualizar_componente(ruta, "nucleo", {"vivo": True})
    actualizar_componente(ruta, "ble", {"vivo": False})
    assert set(leer_estado(ruta)) == {"nucleo", "ble"}
