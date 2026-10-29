"""Lado productor del visor: publica fotogramas sin bloquear a quien los produce.

`PublicadorVisor` guarda solo el último JPEG de cada fuente (ranura sin cola) y un hilo por
fuente lo envía al visor por HTTP en loopback con conexión persistente. Publicar es asignar
una referencia: nunca bloquea los hilos de adquisición ni de detección. También sirve como
almacén local del último fotograma (evidencias y reconocimiento) dentro del proceso.
"""

import http.client
import threading
import time
from collections.abc import Callable

import cv2

from edge_parcial.visor.servidor import FUENTES, HOST, PUERTO

FPS_ENVIO_MAX = 20.0
CALIDAD_LOCAL = 70
TIMEOUT_S = 0.5


def codificar_jpeg(img, calidad: int = CALIDAD_LOCAL) -> bytes | None:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, calidad])
    return buf.tobytes() if ok else None


class PublicadorVisor:
    def __init__(
        self, host: str = HOST, puerto: int = PUERTO, fps_max: float = FPS_ENVIO_MAX
    ) -> None:
        self.host, self.puerto = host, puerto
        self.periodo_s = 1.0 / fps_max
        self._ranura: dict[str, tuple[bytes, float] | None] = dict.fromkeys(FUENTES)
        self._enviado: dict[str, int] = dict.fromkeys(FUENTES, 0)
        self._version: dict[str, int] = dict.fromkeys(FUENTES, 0)
        self._eventos = {f: threading.Event() for f in FUENTES}
        self._parar = threading.Event()
        self._hilos: list[threading.Thread] = []
        self.errores: list[str] = []

    # -- productores --------------------------------------------------------------

    def publicar_jpeg(self, fuente: str, jpeg: bytes) -> None:
        """No bloquea: reemplaza la ranura de la fuente y avisa a su hilo de envío."""
        self._ranura[fuente] = (jpeg, time.monotonic())
        self._version[fuente] += 1
        self._eventos[fuente].set()

    def ultimo(self, fuente: str, max_edad_s: float = 3.0) -> bytes | None:
        r = self._ranura.get(fuente)
        if r is None or time.monotonic() - r[1] > max_edad_s:
            return None
        return r[0]

    # -- ciclo de vida ------------------------------------------------------------

    def iniciar(self) -> None:
        for f in FUENTES:
            h = threading.Thread(
                target=self._enviar, args=(f,), name=f"visor-{f}", daemon=True
            )
            h.start()
            self._hilos.append(h)

    def codificar_periodico(
        self, fuente: str, imagen: Callable[[], object], fps: float = 15.0
    ) -> None:
        """Hilo propio: codifica una sola vez (calidad ~70) la última imagen decodificada."""

        def bucle() -> None:
            visto = None
            while not self._parar.wait(1.0 / fps):
                img = imagen()
                if img is None or img is visto:
                    continue
                visto = img
                jpeg = codificar_jpeg(img)
                if jpeg:
                    self.publicar_jpeg(fuente, jpeg)

        h = threading.Thread(target=bucle, name=f"visor-cod-{fuente}", daemon=True)
        h.start()
        self._hilos.append(h)

    def detener(self) -> None:
        self._parar.set()
        for e in self._eventos.values():
            e.set()
        for h in self._hilos:
            h.join(2)

    # -- envío --------------------------------------------------------------------

    def _enviar(self, fuente: str) -> None:
        con: http.client.HTTPConnection | None = None
        while not self._parar.is_set():
            self._eventos[fuente].wait(1.0)
            self._eventos[fuente].clear()
            version = self._version[fuente]
            r = self._ranura[fuente]
            if r is None or version == self._enviado[fuente]:
                continue
            try:
                if con is None:
                    con = http.client.HTTPConnection(
                        self.host, self.puerto, timeout=TIMEOUT_S
                    )
                con.request(
                    "POST", f"/publicar/{fuente}", r[0], {"Content-Type": "image/jpeg"}
                )
                con.getresponse().read()
                self._enviado[fuente] = version
            except (OSError, http.client.HTTPException) as e:
                if con is not None:
                    con.close()
                con = None
                self.errores = (self.errores + [f"visor: {type(e).__name__}"])[-5:]
                self._parar.wait(1.0)  # visor caído: se reintenta sin saturar
                continue
            self._parar.wait(self.periodo_s)  # tope de fps hacia el visor


def obtener_ultimo(
    fuente: str, max_edad_s: float = 2.0, host: str = HOST, puerto: int = PUERTO
) -> bytes | None:
    """Pide al visor el último fotograma de la fuente (None si no hay uno reciente)."""
    try:
        con = http.client.HTTPConnection(host, puerto, timeout=2.0)
        con.request("GET", f"/ultimo/{fuente}.jpg?max_edad={max_edad_s}")
        r = con.getresponse()
        cuerpo = r.read()
        con.close()
    except OSError, http.client.HTTPException:
        return None
    return cuerpo if r.status == 200 else None


def publicar_una_vez(
    fuente: str, jpeg: bytes, host: str = HOST, puerto: int = PUERTO
) -> bool:
    """Publica un JPEG sin hilo propio (lo usa el simulador). False si el visor no responde."""
    try:
        con = http.client.HTTPConnection(host, puerto, timeout=TIMEOUT_S)
        con.request("POST", f"/publicar/{fuente}", jpeg, {"Content-Type": "image/jpeg"})
        ok = con.getresponse().status == 204
        con.close()
    except OSError, http.client.HTTPException:
        return False
    return ok
