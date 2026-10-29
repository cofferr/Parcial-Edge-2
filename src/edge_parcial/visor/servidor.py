"""Servidor del visor: guarda el ÚLTIMO fotograma JPEG de cada fuente y lo sirve por HTTP.

- POST /publicar/{fuente}   (cuerpo: JPEG)  lo publica el núcleo (o el simulador).
- GET  /stream/{fuente}     multipart/x-mixed-replace (MJPEG) para incrustar en el panel.
- GET  /ultimo/{fuente}.jpg el último fotograma (evidencias y registro de rostros).
El visor nunca abre conexiones a las cámaras y no re-codifica nada: reenvía el payload.
Sin cola: un fotograma nuevo reemplaza al anterior.
"""

import asyncio
import time
from dataclasses import dataclass

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

HOST = "127.0.0.1"  # fijo: el visor nunca se expone fuera de la máquina
PUERTO = 8766
FUENTES = ("esp32", "droidcam", "local")
MAX_EDAD_S = 3.0  # un fotograma más viejo que esto cuenta como «sin señal»
FRONTERA = "frame"


@dataclass
class Ranura:
    jpeg: bytes = b""
    seq: int = 0
    t: float = 0.0  # time.monotonic() de la publicación


def jpeg_sin_senal(texto: str = "sin señal") -> bytes:
    img = np.full((240, 320, 3), 40, np.uint8)
    cv2.putText(
        img, texto, (70, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (200, 200, 200), 2
    )
    ok, buf = cv2.imencode(".jpg", img)
    return buf.tobytes() if ok else b""


def _parte(jpeg: bytes) -> bytes:
    cab = f"--{FRONTERA}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n\r\n"
    return cab.encode() + jpeg + b"\r\n"


def crear_app(max_edad_s: float = MAX_EDAD_S) -> FastAPI:
    app = FastAPI(title="Visor", docs_url=None, redoc_url=None)
    ranuras = {f: Ranura() for f in FUENTES}
    placeholder = jpeg_sin_senal()
    app.state.ranuras = ranuras

    def _fuente(fuente: str) -> Ranura:
        if fuente not in ranuras:
            raise HTTPException(status_code=404, detail=f"Fuente desconocida: {fuente}")
        return ranuras[fuente]

    @app.get("/salud")
    async def salud() -> dict:
        ahora = time.monotonic()
        return {
            "ok": True,
            "edades_s": {
                f: (round(ahora - r.t, 2) if r.seq else None)
                for f, r in ranuras.items()
            },
        }

    @app.post("/publicar/{fuente}")
    async def publicar(fuente: str, request: Request) -> Response:
        r = _fuente(fuente)
        cuerpo = await request.body()
        if not cuerpo.startswith(b"\xff\xd8"):
            raise HTTPException(status_code=400, detail="El cuerpo no es un JPEG")
        r.jpeg, r.t = cuerpo, time.monotonic()
        r.seq += 1
        return Response(status_code=204)

    @app.get("/ultimo/{fuente}.jpg")
    async def ultimo(fuente: str, max_edad: float | None = None) -> Response:
        r = _fuente(fuente)
        limite = max_edad_s if max_edad is None else max_edad
        if not r.seq or time.monotonic() - r.t > limite:
            raise HTTPException(status_code=404, detail="Sin fotograma reciente")
        return Response(
            r.jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"}
        )

    @app.get("/stream/{fuente}")
    async def stream(fuente: str) -> StreamingResponse:
        r = _fuente(fuente)

        async def generar():
            visto = -1
            while True:
                if r.seq and time.monotonic() - r.t <= max_edad_s:
                    if r.seq != visto:
                        visto = r.seq
                        yield _parte(r.jpeg)
                    await asyncio.sleep(0.02)
                else:
                    visto = -1
                    yield _parte(
                        placeholder
                    )  # fuente caída: el navegador muestra «sin señal»
                    await asyncio.sleep(1.0)

        return StreamingResponse(
            generar(),
            media_type=f"multipart/x-mixed-replace; boundary={FRONTERA}",
            headers={"Cache-Control": "no-store"},
        )

    return app
