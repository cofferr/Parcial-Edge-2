"""Gateway BLE: sesión con reconexión (backoff acotado), telemetría y latido.

Sin efectos secundarios al importar: bleak se importa solo al abrir una sesión real.
La fuente BLE es una interfaz (`FuenteBle`) para poder probar con un cliente simulado.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from edge_parcial.ble.foto import guardar_foto
from edge_parcial.ble.telemetria import EscritorTelemetria
from edge_parcial.ble.trama import TramaInvalida, decodificar
from edge_parcial.panel.estado import actualizar_componente, ahora_iso, entrada

log = logging.getLogger("edge_parcial.ble")


@dataclass(frozen=True)
class ParamsBle:
    nombre: str = "EstacionESP32"
    service_uuid: str = "7f3c1a10-5d2b-4e8a-9c41-2b6f0d3e8a01"
    char_uuid: str = "7f3c1a11-5d2b-4e8a-9c41-2b6f0d3e8a01"
    timeout_busqueda_s: float = 20.0
    backoff_inicial_s: float = 1.0
    backoff_max_s: float = 30.0
    latido_s: float = 1.0
    # Cámara a la que se pide la foto cuando hay movimiento; vacío = sin foto.
    url_foto: str = ""
    carpeta_fotos: Path = Path("data/snapshots")


class FuenteBle(Protocol):
    async def sesion(
        self, al_recibir: Callable[[bytes], None], al_conectar: Callable[[], None]
    ) -> None:
        """Busca, conecta y suscribe; vuelve al perderse la conexión.

        Lanza una excepción si no logra conectar.
        """
        ...


class FuenteBleak:
    """Fuente real con bleak (importado de forma diferida)."""

    def __init__(self, params: ParamsBle) -> None:
        self.params = params

    async def sesion(self, al_recibir, al_conectar) -> None:
        from bleak import BleakClient, BleakScanner

        p = self.params
        dispositivo = await BleakScanner.find_device_by_filter(
            lambda d, adv: p.service_uuid in [u.lower() for u in adv.service_uuids],
            timeout=p.timeout_busqueda_s,
        )
        if dispositivo is None:
            raise ConnectionError(f"No se encontró {p.nombre}")
        desconectado = asyncio.Event()
        async with BleakClient(
            dispositivo, disconnected_callback=lambda _: desconectado.set()
        ) as cliente:
            al_conectar()
            await cliente.start_notify(p.char_uuid, lambda _, d: al_recibir(bytes(d)))
            await desconectado.wait()


class Gateway:
    def __init__(
        self,
        fuente: FuenteBle,
        escritor: EscritorTelemetria,
        ruta_estado: Path | str,
        params: ParamsBle | None = None,
        reloj: Callable[[], datetime] | None = None,
    ) -> None:
        self.fuente = fuente
        self.escritor = escritor
        self.ruta_estado = Path(ruta_estado)
        self.params = params or ParamsBle()
        self._reloj = reloj or (lambda: datetime.now().astimezone())
        self._parar = asyncio.Event()
        self.conectado = False
        self.ultima_marca: str | None = None
        self.errores: list[str] = []
        self.lecturas = 0

    def _error(self, mensaje: str) -> None:
        log.warning(mensaje)
        self.errores = (self.errores + [f"{ahora_iso()} {mensaje}"])[-5:]

    def al_recibir(self, datos: bytes) -> None:
        try:
            lectura = decodificar(datos)
        except TramaInvalida as e:
            self._error(f"{e}: {datos.hex(' ')}")
            return
        ahora = self._reloj()
        foto = ""
        if lectura.movimiento == 1 and self.params.url_foto:
            foto = f"foto_{ahora.strftime('%Y%m%d_%H%M%S')}.jpg"
            self._pedir_foto(foto)
        self.escritor.agregar(ahora, lectura, datos, foto)
        self.lecturas += 1
        self.ultima_marca = ahora.isoformat(timespec="milliseconds")

    def _pedir_foto(self, nombre: str) -> None:
        # En otro hilo: la petición HTTP no debe frenar la recepción de tramas BLE.
        def tarea() -> None:
            try:
                guardar_foto(self.params.url_foto, self.params.carpeta_fotos / nombre)
            except Exception as e:  # noqa: BLE001 - la foto es accesoria
                self._error(f"No se pudo guardar la foto: {e}")

        asyncio.get_running_loop().run_in_executor(None, tarea)

    def _al_conectar(self) -> None:
        self.conectado = True

    def detener(self) -> None:
        self._parar.set()

    def publicar_estado(self) -> None:
        try:
            actualizar_componente(
                self.ruta_estado,
                "ble",
                entrada(self.conectado, None, self.ultima_marca, self.errores),
            )
        except OSError as e:  # el latido nunca debe tumbar el gateway
            log.warning("No se pudo escribir el estado: %s", e)

    async def _latido(self) -> None:
        while True:
            self.publicar_estado()
            await asyncio.sleep(self.params.latido_s)

    async def _esperar(self, segundos: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._parar.wait(), segundos)

    async def ejecutar(self) -> None:
        latido = asyncio.create_task(self._latido())
        espera = self.params.backoff_inicial_s
        try:
            while not self._parar.is_set():
                self.conectado = False
                sesion = asyncio.create_task(
                    self.fuente.sesion(self.al_recibir, self._al_conectar)
                )
                parar = asyncio.create_task(self._parar.wait())
                await asyncio.wait({sesion, parar}, return_when=asyncio.FIRST_COMPLETED)
                if not sesion.done():
                    sesion.cancel()
                    with contextlib.suppress(BaseException):
                        await sesion
                    break
                parar.cancel()
                hubo_sesion = self.conectado
                try:
                    sesion.result()  # propaga el error si no pudo conectar
                    self._error("Conexión perdida")
                except Exception as e:  # noqa: BLE001 - se reintenta con backoff
                    self._error(f"{type(e).__name__}: {e}")
                self.conectado = False
                self.publicar_estado()
                if hubo_sesion:
                    espera = self.params.backoff_inicial_s  # hubo sesión: se reinicia
                await self._esperar(espera)
                espera = min(espera * 2, self.params.backoff_max_s)
        finally:
            self.conectado = False
            latido.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await latido
            self.publicar_estado()
