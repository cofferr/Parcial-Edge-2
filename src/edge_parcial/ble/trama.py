"""Decodificación de la trama BLE de 7 bytes, little-endian: "<hHHB"."""

import struct
from dataclasses import dataclass

FORMATO = "<hHHB"
LONGITUD = struct.calcsize(FORMATO)
SUELO_SIN_SENSOR = 0xFFFF


class TramaInvalida(ValueError):
    """La trama no mide 7 bytes."""


@dataclass(frozen=True)
class Lectura:
    temperatura_c: float
    humedad_pct: float
    suelo_adc: int | None  # None = sin sensor (0xFFFF)
    movimiento: int


def decodificar(datos: bytes) -> Lectura:
    if len(datos) != LONGITUD:
        raise TramaInvalida(f"Trama de {len(datos)} bytes (se esperaban {LONGITUD})")
    temp_x100, hum_x100, suelo, mov = struct.unpack(FORMATO, datos)
    return Lectura(
        temperatura_c=temp_x100 / 100,
        humedad_pct=hum_x100 / 100,
        suelo_adc=None if suelo == SUELO_SIN_SENSOR else suelo,
        movimiento=mov,
    )
