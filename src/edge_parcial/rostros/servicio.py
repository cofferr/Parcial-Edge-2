"""Servicio HTTP de reconocimiento facial, solo en 127.0.0.1.

POST /reconocer?fuente=esp32  (cuerpo: un JPEG)  ->  JSON con las caras.
La imagen se reduce con el factor de la fuente antes de analizarla y las cajas se
devuelven en los píxeles de la imagen original.
"""

import collections
import contextlib
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request

from edge_parcial.panel.estado import actualizar_componente, ahora_iso, entrada
from edge_parcial.rostros.reconocedor import Reconocedor

HOST = "127.0.0.1"  # fijo: el servicio nunca se expone fuera de la máquina
PUERTO = 8765

# Factor de reducción por fuente. El 0,25 de la app original deja una imagen de 80x60
# con 320x240 y no detecta nada; la ESP32 se analiza sin reducir.
FACTORES_DEFECTO = {"esp32": 1.0, "droidcam": 0.5, "local": 0.25}
FACTOR_OTRAS = 0.5


@dataclass
class Estadisticas:
    marcas: collections.deque = field(
        default_factory=lambda: collections.deque(maxlen=200)
    )
    errores: list[str] = field(default_factory=list)
    ultima_marca: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def registrar(self) -> None:
        with self.lock:
            self.marcas.append(time.monotonic())
            self.ultima_marca = ahora_iso()

    def error(self, mensaje: str) -> None:
        with self.lock:
            self.errores = (self.errores + [f"{ahora_iso()} {mensaje}"])[-5:]

    def fps(self, ventana_s: float = 5.0) -> float:
        corte = time.monotonic() - ventana_s
        with self.lock:
            n = sum(1 for m in self.marcas if m >= corte)
        return round(n / ventana_s, 2)


def crear_app(
    reconocedor: Reconocedor,
    factores: dict[str, float] | None = None,
    ruta_estado: Path | str | None = None,
) -> FastAPI:
    factores = {**FACTORES_DEFECTO, **(factores or {})}
    for f in factores.values():
        if not 0 < f <= 1:
            raise ValueError(f"Factor de reducción fuera de (0, 1]: {f}")
    stats = Estadisticas()

    def publicar() -> None:
        if ruta_estado is None:
            return
        try:
            actualizar_componente(
                ruta_estado,
                "servicio_rostros",
                entrada(True, stats.fps(), stats.ultima_marca, stats.errores),
            )
        except OSError as e:
            stats.error(f"estado.json: {e}")

    @contextlib.asynccontextmanager
    async def vida(_: FastAPI):
        publicar()
        parar = threading.Event()

        def latido() -> None:
            while not parar.wait(1.0):
                publicar()

        threading.Thread(target=latido, daemon=True).start()
        yield
        parar.set()

    app = FastAPI(
        title="Servicio de rostros", docs_url=None, redoc_url=None, lifespan=vida
    )
    app.state.stats = stats

    @app.get("/salud")
    def salud() -> dict:
        return {"ok": True, "reconocedor": reconocedor.nombre}

    @app.post("/reconocer")
    async def reconocer(request: Request, fuente: str = Query(...)) -> dict:
        cuerpo = await request.body()
        imagen = cv2.imdecode(np.frombuffer(cuerpo, np.uint8), cv2.IMREAD_COLOR)
        if imagen is None:
            stats.error("JPEG inválido")
            raise HTTPException(
                status_code=400, detail="El cuerpo no es un JPEG válido"
            )
        factor = factores.get(fuente, FACTOR_OTRAS)
        recargar = getattr(reconocedor, "recargar_si_cambio", None)
        if recargar is not None:
            try:
                recargar()
            except OSError as e:
                stats.error(f"recarga de rostros: {e}")
        t0 = time.perf_counter()
        if factor != 1.0:
            imagen = cv2.resize(
                imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA
            )
        rgb = cv2.cvtColor(imagen, cv2.COLOR_BGR2RGB)
        try:
            detecciones = reconocedor.reconocer(rgb)
        except Exception as e:
            stats.error(f"{type(e).__name__}: {e}")
            raise HTTPException(status_code=500, detail="Fallo al reconocer") from e
        stats.registrar()
        caras = []
        for d in detecciones:
            top, right, bottom, left = (round(v / factor) for v in d.caja)
            caras.append(
                {
                    "identidad": d.identidad,
                    "distancia": None if d.distancia is None else round(d.distancia, 4),
                    "caja": {
                        "top": top,
                        "right": right,
                        "bottom": bottom,
                        "left": left,
                    },
                }
            )
        return {
            "fuente": fuente,
            "factor": factor,
            "caras": caras,
            "ms": round((time.perf_counter() - t0) * 1000, 2),
        }

    return app
