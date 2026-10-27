"""Parser incremental de MJPEG (multipart/x-mixed-replace) o de una respuesta HTTP.

No usa sockets: recibe trozos con la marca de tiempo (perf_counter_ns) del recv que
los trajo y devuelve fotogramas completos. Así se prueba con trozos arbitrarios.

Definiciones de tiempo (ver docs/DISENO.md):
- t_first: marca del recv que contenía el primer byte de la parte (delimitador
  multipart; en una respuesta HTTP, el primer byte de la línea de estado).
- t_last: marca del recv que contenía el último byte de la carga JPEG.
- Ambas son cotas superiores del arribo real: el error máximo es una lectura (recv).
  Si t_first y t_last caen en el mismo recv (n_recv == 1), ttx = 0 es solo el límite
  de resolución, no un tiempo de transmisión real.
"""

from bisect import bisect_right
from dataclasses import dataclass, field

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"

MAX_CABECERA = 65536
MAX_PAYLOAD = 16 * 1024 * 1024


class ErrorProtocolo(Exception):
    """El flujo no cumple el formato esperado (HTTP/multipart/JPEG)."""


@dataclass(frozen=True)
class Fotograma:
    payload: bytes
    t_first_ns: int
    t_last_ns: int
    n_recv: int  # recv desde el que contiene t_first hasta el que contiene t_last
    header_bytes: int  # delimitador + cabeceras de la parte (o cabecera HTTP)
    cabeceras: dict = field(default_factory=dict)  # claves en minúsculas
    jpeg_valid: bool = True
    error: str | None = None


def jpeg_valido(payload: bytes) -> bool:
    """SOI al inicio y EOI al final."""
    return len(payload) >= 4 and payload[:2] == SOI and payload[-2:] == EOI


class _Recorrido:
    """Recorrido reanudable de marcadores JPEG para hallar el EOI sin Content-Length.

    Salta segmentos por su longitud y, dentro del scan, los FF00 y RSTn. Así un
    FFD9 dentro de una miniatura incrustada (APPn) no se confunde con el EOI.
    """

    def __init__(self) -> None:
        self.pos = 0
        self.modo = "SOI"  # SOI -> MARCADOR <-> SCAN
        self.fin: int | None = None
        self.corrupto: str | None = None

    def avanzar(self, buf: bytearray) -> None:
        n = len(buf)
        while self.fin is None and self.corrupto is None:
            if self.modo == "SOI":
                if n < 2:
                    return
                if buf[:2] != SOI:
                    self.corrupto = "falta SOI"
                    return
                self.pos = 2
                self.modo = "MARCADOR"
            elif self.modo == "MARCADOR":
                if self.pos + 2 > n:
                    return
                if buf[self.pos] != 0xFF:
                    self.corrupto = f"se esperaba marcador en {self.pos}"
                    return
                m = buf[self.pos + 1]
                if m == 0xFF:  # relleno
                    self.pos += 1
                elif m == 0xD9:
                    self.fin = self.pos + 2
                elif m == 0x00:
                    self.corrupto = f"marcador FF00 inválido en {self.pos}"
                    return
                elif m == 0x01 or 0xD0 <= m <= 0xD8:  # sin longitud
                    self.pos += 2
                else:
                    if self.pos + 4 > n:
                        return
                    largo = (buf[self.pos + 2] << 8) | buf[self.pos + 3]
                    if largo < 2:
                        self.corrupto = f"longitud de segmento inválida en {self.pos}"
                        return
                    if self.pos + 2 + largo > n:
                        return  # esperar el segmento completo
                    self.pos += 2 + largo
                    if m == 0xDA:
                        self.modo = "SCAN"
            else:  # SCAN: datos entropy-coded hasta el próximo marcador real
                i = buf.find(b"\xff", self.pos)
                if i < 0:
                    self.pos = n
                    return
                if i + 1 >= n:
                    self.pos = i
                    return
                s = buf[i + 1]
                if s == 0x00 or 0xD0 <= s <= 0xD7:
                    self.pos = i + 2
                elif s == 0xFF:
                    self.pos = i + 1
                else:
                    self.pos = i
                    self.modo = "MARCADOR"


class ParserMJPEG:
    """Parser de una conexión.

    tipo="stream": cabecera HTTP + partes multipart sucesivas.
    tipo="captura": cabecera HTTP + un único cuerpo JPEG (Content-Length o hasta
    el cierre de la conexión, ver `fin_de_flujo`).
    """

    def __init__(self, tipo: str = "stream", max_payload: int = MAX_PAYLOAD) -> None:
        if tipo not in ("stream", "captura"):
            raise ValueError(f"tipo desconocido: {tipo}")
        self.tipo = tipo
        self.max_payload = max_payload
        self.http_status: int | None = None
        self.http_cabeceras: dict = {}
        self.bytes_totales = 0
        self._buf = bytearray()
        self._base = 0  # offset absoluto del primer byte de _buf
        # Un renglón por recv: offset absoluto donde termina, marca y número de recv.
        self._fines: list[int] = []
        self._marcas: list[int] = []
        self._ids: list[int] = []
        self._n_recv = 0
        self._estado = "HEAD"
        self._delim: bytes | None = None
        self._parte: dict = {}
        self._recorrido: _Recorrido | None = None
        self._fallback = False

    # -- API pública -------------------------------------------------------

    def feed(self, datos, t_ns: int) -> list[Fotograma]:
        """Procesa un trozo recibido en el instante t_ns (tomado tras recv_into)."""
        if len(datos) == 0:
            return []
        self._buf += datos
        self.bytes_totales += len(datos)
        self._fines.append(self._base + len(self._buf))
        self._marcas.append(t_ns)
        self._ids.append(self._n_recv)
        self._n_recv += 1
        return self._avanzar()

    def fin_de_flujo(self) -> list[Fotograma]:
        """El servidor cerró la conexión. Cierra una captura sin Content-Length."""
        if (
            self._estado == "CUERPO"
            and self.tipo == "captura"
            and not self._parte["cl"]
        ):
            if not self._buf:
                raise ErrorProtocolo("respuesta sin cuerpo")
            return [self._emitir(len(self._buf))]
        return []

    def bytes_pendientes(self) -> int:
        """Bytes recibidos de un fotograma incompleto (incluye su cabecera ya leída)."""
        if self._estado == "CUERPO":
            return self._parte["header_bytes"] + len(self._buf)
        if self._estado == "PARTE":
            k = 0
            while k < len(self._buf) and self._buf[k] in (13, 10):
                k += 1
            return len(self._buf) - k
        return 0

    @property
    def delimitador(self) -> bytes | None:
        return self._delim

    # -- tiempos -----------------------------------------------------------

    def _recv_de(self, rel: int) -> tuple[int, int]:
        """(marca, id de recv) del recv que contenía el byte en rel (relativo a _buf)."""
        i = bisect_right(self._fines, self._base + rel)
        return self._marcas[i], self._ids[i]

    def _consumir(self, k: int) -> None:
        del self._buf[:k]
        self._base += k
        i = bisect_right(self._fines, self._base)  # recv ya totalmente consumidos
        if i:
            del self._fines[:i], self._marcas[:i], self._ids[:i]

    # -- máquina de estados ------------------------------------------------

    def _avanzar(self) -> list[Fotograma]:
        salida: list[Fotograma] = []
        while True:
            if self._estado == "HEAD":
                if not self._paso_head():
                    break
            elif self._estado == "PARTE":
                if not self._paso_parte():
                    break
            elif self._estado == "CUERPO":
                f = self._paso_cuerpo()
                if f is None:
                    break
                salida.append(f)
            else:  # FIN
                self._consumir(len(self._buf))
                break
        return salida

    def _paso_head(self) -> bool:
        i = self._buf.find(b"\r\n\r\n")
        if i < 0:
            if len(self._buf) > MAX_CABECERA:
                raise ErrorProtocolo("cabecera HTTP demasiado larga")
            return False
        lineas = bytes(self._buf[:i]).decode("latin-1").split("\r\n")
        partes = lineas[0].split(" ", 2)
        if (
            len(partes) < 2
            or not partes[0].startswith("HTTP/")
            or not partes[1].isdigit()
        ):
            raise ErrorProtocolo(f"línea de estado inválida: {lineas[0]!r}")
        self.http_status = int(partes[1])
        self.http_cabeceras = _parsear_cabeceras(lineas[1:])
        if self.http_status != 200:
            raise ErrorProtocolo(f"HTTP {self.http_status}")
        if "chunked" in self.http_cabeceras.get("transfer-encoding", "").lower():
            raise ErrorProtocolo("Transfer-Encoding: chunked no soportado")
        t_first, id_first = self._recv_de(0)
        if self.tipo == "captura":
            self._parte = {
                "t_first": t_first,
                "id_first": id_first,
                "header_bytes": i + 4,
                "cabeceras": self.http_cabeceras,
                "cl": _entero(self.http_cabeceras.get("content-length")),
            }
            self._consumir(i + 4)
            self._estado = "CUERPO"
            self._iniciar_cuerpo()
            return True
        ct = self.http_cabeceras.get("content-type", "")
        if ct:
            if "multipart" not in ct.lower():
                raise ErrorProtocolo(f"Content-Type no multipart: {ct!r}")
            for p in ct.split(";")[1:]:
                k, _, v = p.strip().partition("=")
                if k.lower() == "boundary" and v:
                    self._delim = b"--" + v.strip('"').encode("latin-1")
        self._consumir(i + 4)
        self._estado = "PARTE"
        return True

    def _paso_parte(self) -> bool:
        k = 0
        while k < len(self._buf) and self._buf[k] in (13, 10):
            k += 1
        if k:
            self._consumir(k)
        if not self._buf:
            return False
        if self._delim is None:  # sin boundary en la cabecera: se toma de la 1.ª línea
            j = self._buf.find(b"\r\n")
            if j < 0:
                return False
            linea = bytes(self._buf[:j]).rstrip()
            if not linea.startswith(b"--"):
                raise ErrorProtocolo(f"se esperaba delimitador, llegó {linea[:20]!r}")
            self._delim = linea
        d = self._delim
        m = min(len(self._buf), len(d))
        if self._buf[:m] != d[:m]:
            raise ErrorProtocolo(f"se esperaba {d!r}, llegó {bytes(self._buf[:m])!r}")
        if len(self._buf) < len(d) + 2:
            return False
        if self._buf[len(d) : len(d) + 2] == b"--":
            self._estado = "FIN"
            return True
        j = self._buf.find(b"\r\n\r\n", len(d))
        if j < 0:
            if len(self._buf) > MAX_CABECERA:
                raise ErrorProtocolo("cabeceras de parte demasiado largas")
            return False
        t_first, id_first = self._recv_de(0)
        lineas = bytes(self._buf[len(d) : j]).decode("latin-1").split("\r\n")
        cab = _parsear_cabeceras(lineas)
        self._parte = {
            "t_first": t_first,
            "id_first": id_first,
            "header_bytes": j + 4,
            "cabeceras": cab,
            "cl": _entero(cab.get("content-length")),
        }
        self._consumir(j + 4)
        self._estado = "CUERPO"
        self._iniciar_cuerpo()
        return True

    def _iniciar_cuerpo(self) -> None:
        cl = self._parte["cl"]
        # Con Content-Length se usan exactamente N bytes: no se recorre el JPEG.
        self._recorrido = None if cl else _Recorrido()
        self._fallback = False

    def _paso_cuerpo(self) -> Fotograma | None:
        cl = self._parte["cl"]
        if len(self._buf) > self.max_payload:
            raise ErrorProtocolo("carga mayor al máximo permitido")
        if cl:
            if len(self._buf) < cl:
                return None
            return self._emitir(cl)
        if self.tipo == "captura":
            return None  # termina con fin_de_flujo
        if not self._fallback:
            assert self._recorrido is not None
            self._recorrido.avanzar(self._buf)
            if self._recorrido.fin is not None:
                return self._emitir(self._recorrido.fin)
            if self._recorrido.corrupto is None:
                return None
            self._fallback = True
        # JPEG corrupto sin Content-Length: la carga llega hasta el próximo delimitador.
        j = self._buf.find(b"\r\n" + (self._delim or b"--"))
        if j < 0:
            return None
        if j == 0:
            raise ErrorProtocolo("parte vacía")
        return self._emitir(j, error=f"JPEG corrupto: {self._recorrido.corrupto}")

    def _emitir(self, largo: int, error: str | None = None) -> Fotograma:
        payload = bytes(self._buf[:largo])
        t_last, id_last = self._recv_de(largo - 1)
        p = self._parte
        valido = jpeg_valido(payload) and error is None  # error = estructura corrupta
        if not valido and error is None:
            error = "SOI/EOI ausente"
        f = Fotograma(
            payload=payload,
            t_first_ns=p["t_first"],
            t_last_ns=t_last,
            n_recv=id_last - p["id_first"] + 1,
            header_bytes=p["header_bytes"],
            cabeceras=p["cabeceras"],
            jpeg_valid=valido,
            error=error,
        )
        self._consumir(largo)
        self._estado = "PARTE" if self.tipo == "stream" else "FIN"
        return f


def _parsear_cabeceras(lineas: list[str]) -> dict:
    cab = {}
    for linea in lineas:
        k, sep, v = linea.partition(":")
        if sep and k.strip():
            cab[k.strip().lower()] = v.strip()
    return cab


def _entero(valor: str | None) -> int | None:
    try:
        n = int(valor) if valor is not None else None
    except ValueError:
        return None
    return n if n is not None and n > 0 else None
