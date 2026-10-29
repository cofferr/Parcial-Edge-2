"""Cliente HTTP del servicio de rostros (127.0.0.1)."""

import http.client
import json

from edge_parcial.rostros.servicio import HOST, PUERTO

TIMEOUT_S = 15.0  # el reconocimiento facial (dlib) puede tardar


def consultar_servicio(jpeg: bytes, fuente: str, puerto: int = PUERTO) -> list[dict]:
    """POST /reconocer: devuelve las caras. Lanza OSError/ValueError si falla."""
    con = http.client.HTTPConnection(HOST, puerto, timeout=TIMEOUT_S)
    try:
        con.request(
            "POST", f"/reconocer?fuente={fuente}", jpeg, {"Content-Type": "image/jpeg"}
        )
        r = con.getresponse()
        cuerpo = r.read()
    finally:
        con.close()
    if r.status != 200:
        raise OSError(f"servicio de rostros respondió {r.status}")
    return list(json.loads(cuerpo).get("caras", []))
