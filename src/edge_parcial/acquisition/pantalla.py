"""Salida de ventanas OpenCV. macOS exige dibujar desde el hilo principal.

`Pantalla` es la interfaz mínima; `PantallaCV2` la implementa con cv2.imshow/waitKey y
las pruebas usan una pantalla falsa.
"""

from typing import Protocol

import cv2

TECLA_Q = ord("q")


class Pantalla(Protocol):
    def mostrar(self, nombre: str, frame) -> None: ...

    def tecla(self, espera_ms: int) -> int:
        """Código de la tecla pulsada o -1."""

    def visible(self, nombre: str) -> bool:
        """False si el usuario cerró la ventana (solo tras haberla mostrado)."""

    def cerrar(self) -> None: ...


class PantallaCV2:
    def __init__(self) -> None:
        self._mostradas: set[str] = set()

    def mostrar(self, nombre: str, frame) -> None:
        cv2.imshow(nombre, frame)
        self._mostradas.add(nombre)

    def tecla(self, espera_ms: int) -> int:
        return cv2.waitKey(max(1, espera_ms)) & 0xFF if espera_ms >= 0 else -1

    def visible(self, nombre: str) -> bool:
        if nombre not in self._mostradas:
            return True
        return cv2.getWindowProperty(nombre, cv2.WND_PROP_VISIBLE) >= 1

    def cerrar(self) -> None:
        cv2.destroyAllWindows()
        cv2.waitKey(1)  # macOS necesita un ciclo de eventos para cerrar las ventanas
