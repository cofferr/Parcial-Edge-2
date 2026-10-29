"""Registro de rostros conocidos (lógica portada de `capturar_rostro` de facial_recognition.py).

Una persona = una carpeta `rostros_conocidos/<nombre>/` con una o varias muestras JPEG. Se
rechaza toda muestra que no tenga EXACTAMENTE un rostro. La carpeta está fuera de git.
"""

import re
import shutil
from pathlib import Path

import cv2
import numpy as np

from edge_parcial.rostros.reconocedor import CARPETA_ROSTROS, LOCK_DLIB

NOMBRE_VALIDO = re.compile(r"^[\wáéíóúüñÁÉÍÓÚÜÑ][\wáéíóúüñÁÉÍÓÚÜÑ .-]{0,39}$")


class ErrorRegistro(ValueError):
    """Muestra o nombre rechazados (el mensaje es para el usuario)."""


def contar_rostros(bgr: np.ndarray) -> int:
    """Cantidad de rostros detectados (face_recognition, serializado con el lock de dlib)."""
    import face_recognition

    rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    with LOCK_DLIB:
        return len(face_recognition.face_locations(rgb))


def validar_nombre(nombre: str) -> str:
    nombre = nombre.strip()
    if not NOMBRE_VALIDO.match(nombre) or nombre.endswith(".") or ".." in nombre:
        raise ErrorRegistro(
            "Nombre no válido: usa letras, números, espacios, guion o punto (máx. 40)."
        )
    return nombre


def decodificar(datos: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(datos, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ErrorRegistro("La imagen no se pudo leer (usa JPG o PNG).")
    return img


def agregar_muestra(
    nombre: str,
    imagen: bytes,
    carpeta: Path | str = CARPETA_ROSTROS,
    contar=contar_rostros,
) -> Path:
    """Valida y guarda una muestra. Lanza ErrorRegistro si no hay exactamente un rostro."""
    nombre = validar_nombre(nombre)
    bgr = decodificar(imagen)
    n = contar(bgr)
    if n == 0:
        raise ErrorRegistro("No se detectó ningún rostro: acércate o mejora la luz.")
    if n > 1:
        raise ErrorRegistro(f"Se detectaron {n} rostros: debe haber solo uno.")
    destino = Path(carpeta) / nombre
    destino.mkdir(parents=True, exist_ok=True)
    siguiente = 1 + max(
        (int(p.stem) for p in destino.glob("*.jpg") if p.stem.isdigit()), default=0
    )
    ruta = destino / f"{siguiente}.jpg"
    if not cv2.imwrite(str(ruta), bgr):
        raise ErrorRegistro("No se pudo guardar la muestra en disco.")
    return ruta


def listar(carpeta: Path | str = CARPETA_ROSTROS) -> dict[str, int]:
    """Persona -> número de muestras (incluye los `Nombre.jpg` sueltos de la app original)."""
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        return {}
    personas: dict[str, int] = {}
    for e in sorted(carpeta.iterdir()):
        if e.is_dir():
            n = sum(
                1 for a in e.iterdir() if a.suffix.lower() in (".jpg", ".jpeg", ".png")
            )
            if n:
                personas[e.name] = n
        elif e.suffix.lower() in (".jpg", ".jpeg", ".png"):
            personas[e.stem] = personas.get(e.stem, 0) + 1
    return personas


def borrar(nombre: str, carpeta: Path | str = CARPETA_ROSTROS) -> int:
    """Borra todas las muestras de la persona; devuelve cuántos archivos eliminó."""
    nombre = validar_nombre(nombre)
    carpeta = Path(carpeta)
    borrados = 0
    destino = carpeta / nombre
    if destino.is_dir():
        borrados += sum(1 for a in destino.iterdir() if a.is_file())
        shutil.rmtree(destino)
    for e in carpeta.glob(f"{nombre}.*"):
        if e.is_file() and e.stem == nombre:
            e.unlink()
            borrados += 1
    return borrados
