"""Opción `--ventanas`: las tres cámaras con la superposición del voto (hilo principal).

Cada ventana muestra el voto de la última ventana decidida (el mismo que el log y
eventos.csv), su estado (movimiento, tapada, sin_datos...) y, al pie, Q, el número de
votos True y un banner ALERTA cuando se dispara. Pensada para capturas de pantalla.
"""

import cv2
import numpy as np

from edge_parcial.acquisition.pantalla import TECLA_Q, Pantalla

ANCHO = 640
ALTO_PLACEHOLDER = 360
VERDE, ROJO, GRIS, BLANCO, NEGRO = (60, 200, 60), (40, 40, 220), (150, 150, 150), (255, 255, 255), (0, 0, 0)  # fmt: skip
FUENTE = cv2.FONT_HERSHEY_SIMPLEX


def _texto(img, txt, pos, escala, color, grosor=2):
    cv2.putText(img, txt, pos, FUENTE, escala, NEGRO, grosor + 3, cv2.LINE_AA)
    cv2.putText(img, txt, pos, FUENTE, escala, color, grosor, cv2.LINE_AA)


def base_fuente(img: np.ndarray | None) -> np.ndarray:
    """Imagen BGR de ancho fijo (con placeholder si la fuente no entrega)."""
    if img is None:
        lienzo = np.zeros((ALTO_PLACEHOLDER, ANCHO, 3), np.uint8)
        _texto(lienzo, "SIN SENAL", (ANCHO // 2 - 90, ALTO_PLACEHOLDER // 2), 0.9, GRIS)
        return lienzo
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    alto = max(1, round(img.shape[0] * ANCHO / img.shape[1]))
    return cv2.resize(img, (ANCHO, alto), interpolation=cv2.INTER_AREA)


def dibujar_fuente(
    img, nombre: str, voto, bandera, ventana, q: int, n_true, alerta: bool
) -> np.ndarray:
    """Superposición de una fuente: voto, estado, pie con Q y votos True, banner ALERTA."""
    lienzo = base_fuente(img)
    alto = lienzo.shape[0]
    _texto(lienzo, nombre.upper(), (10, 30), 0.9, BLANCO)
    if voto is None:
        _texto(lienzo, "VOTO: -   (esperando la primera ventana)", (10, 65), 0.7, GRIS)
    else:
        _texto(lienzo, f"VOTO: {'True' if voto else 'False'}", (10, 65), 0.9, VERDE if voto else ROJO)  # fmt: skip
        _texto(lienzo, f"estado: {bandera}", (10, 95), 0.7, BLANCO)
    cv2.rectangle(lienzo, (0, alto - 38), (ANCHO, alto), NEGRO, -1)
    ventana_txt = "-" if ventana is None else f"{ventana}"
    votos_txt = "-" if n_true is None else f"{n_true}"
    _texto(lienzo, f"Q = {q}   votos True = {votos_txt}   ventana {ventana_txt}", (10, alto - 12), 0.65, BLANCO)  # fmt: skip
    if alerta:
        cv2.rectangle(lienzo, (0, 110), (ANCHO, 175), ROJO, -1)
        _texto(lienzo, "ALERTA", (ANCHO // 2 - 110, 160), 1.8, BLANCO, 4)
    return lienzo


def ejecutar_ventanas(
    nucleo,
    pantalla: Pantalla,
    parar=lambda: False,
    espera_ms: int = 30,
    max_iteraciones: int | None = None,
) -> str:
    """Bucle del hilo principal. Devuelve el motivo de cierre."""
    motivo = "límite de iteraciones"
    nombres = {f: f"Quorum {f}" for f in nucleo.fuentes}
    i = 0
    while max_iteraciones is None or i < max_iteraciones:
        i += 1
        est = nucleo.estado_visual()
        for f, e in est["fuentes"].items():
            pantalla.mostrar(
                nombres[f],
                dibujar_fuente(
                    e["img"],
                    f,
                    e["voto"],
                    e["bandera"],
                    est["ventana"],
                    est["q"],
                    est["n_true"],
                    est["alerta"],
                ),
            )
        if pantalla.tecla(espera_ms) in (TECLA_Q, ord("Q")):
            return "tecla q"
        if parar():
            return "parada solicitada"
        if any(not pantalla.visible(n) for n in nombres.values()):
            return "ventana cerrada"
    return motivo
