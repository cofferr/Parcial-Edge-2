"""Dibuja sobre las fotos el cuadro con el nombre (portado de `dibujar_rostro` de la app original).

Verde con el nombre si la persona es conocida; rojo y «Rostro Desconocido» si no. Las cajas
llegan en píxeles de la imagen original (así las devuelve el servicio de rostros).
"""

import cv2
import numpy as np

COLOR_CONOCIDO = (0, 255, 0)  # BGR
COLOR_DESCONOCIDO = (0, 0, 255)
DESCONOCIDO = "desconocido"
ETIQUETA_DESCONOCIDO = "Rostro Desconocido"
ALTO_REFERENCIA = 480  # la app original escala el trazo respecto a 480 px de alto


def dibujar_caras(bgr: np.ndarray, caras: list[dict]) -> np.ndarray:
    """Copia de la imagen con un cuadro por cara: `{"identidad": str, "caja": {top,...}}`."""
    img = bgr.copy()
    escala = max(img.shape[0] / ALTO_REFERENCIA, 0.5)
    grosor_linea = max(1, round(2 * escala))
    grosor_fuente = max(1, round(escala))
    alto_etiqueta = round(25 * escala)
    for c in caras:
        nombre = str(c.get("identidad", DESCONOCIDO))
        conocido = nombre != DESCONOCIDO
        color = COLOR_CONOCIDO if conocido else COLOR_DESCONOCIDO
        caja = c["caja"]
        top, right, bottom, left = (
            caja["top"],
            caja["right"],
            caja["bottom"],
            caja["left"],
        )
        cv2.rectangle(img, (left, top), (right, bottom), color, grosor_linea)
        cv2.rectangle(
            img, (left, bottom - alto_etiqueta), (right, bottom), color, cv2.FILLED
        )
        cv2.putText(
            img,
            nombre if conocido else ETIQUETA_DESCONOCIDO,
            (left + 6, bottom - 6),
            cv2.FONT_HERSHEY_DUPLEX,
            0.6 * escala,
            (255, 255, 255),
            grosor_fuente,
        )
    return img


def anotar_jpeg(jpeg: bytes, caras: list[dict], calidad: int = 90) -> bytes | None:
    """JPEG con los cuadros dibujados, o None si la imagen no se puede leer o codificar."""
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    ok, buf = cv2.imencode(
        ".jpg", dibujar_caras(img, caras), [cv2.IMWRITE_JPEG_QUALITY, calidad]
    )
    return buf.tobytes() if ok else None
