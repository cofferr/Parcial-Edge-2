"""Simulador de datos del sistema integrado (para desarrollar y probar el panel).

Escribe, siguiendo docs/CONTRATO_DATOS.md: telemetria.csv, eventos.csv,
reconocimientos.csv, snapshots/ y estado.json. Los snapshots son imágenes sintéticas
(sin rostros reales). Nada aquí usa hardware.
"""

import random
import time
from datetime import datetime

import cv2
import numpy as np

from edge_parcial.panel.control import MARCA_DESACTIVADO, quorum_activo
from edge_parcial.panel.datos import (
    COLUMNAS_EVENTOS,
    COLUMNAS_RECONOCIMIENTOS,
    COLUMNAS_TELEMETRIA,
    FUENTES,
    EscritorCSV,
    Rutas,
)
from edge_parcial.panel.estado import COMPONENTES, entrada, escribir_estado
from edge_parcial.visor.cliente import publicar_una_vez

IDENTIDADES = ("Ana", "Luis", "desconocido")
CICLO_MOVIMIENTO_S = (
    20  # cada ciclo, los primeros CICLO_ACTIVO_S segundos hay movimiento
)
CICLO_ACTIVO_S = 6


def imagen_sintetica(fuente: str, identidad: str, ts: datetime) -> bytes:
    """JPEG 320x240 con texto: no contiene rostros."""
    img = np.full((240, 320, 3), 60, np.uint8)
    cv2.circle(img, (160, 110), 50, (200, 200, 200), 2)
    cv2.putText(
        img,
        f"SIMULADO {fuente}",
        (10, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255,) * 3,
        1,
    )
    cv2.putText(
        img, identidad, (10, 215), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2
    )
    cv2.putText(
        img,
        ts.strftime("%H:%M:%S"),
        (230, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255,) * 3,
        1,
    )
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


class Simulador:
    def __init__(
        self, rutas: Rutas, semilla: int | None = None, run_id: str = "sim"
    ) -> None:
        self.rutas = rutas
        self.rng = random.Random(semilla)
        self.run_id = run_id
        self.ventana = 0
        self.temp = 22.0
        self.hum = 55.0
        rutas.snapshots.mkdir(parents=True, exist_ok=True)
        self.telemetria = EscritorCSV(rutas.telemetria, COLUMNAS_TELEMETRIA)
        self.eventos = EscritorCSV(rutas.eventos, COLUMNAS_EVENTOS)
        self.reconocimientos = EscritorCSV(
            rutas.reconocimientos, COLUMNAS_RECONOCIMIENTOS
        )

    def paso(self, ahora: datetime | None = None) -> dict:
        """Genera un segundo de datos; devuelve un resumen (útil en pruebas)."""
        ahora = ahora or datetime.now().astimezone()
        self.ventana += 1
        r = self.rng
        self.temp += r.uniform(-0.15, 0.15)
        self.hum = min(95.0, max(20.0, self.hum + r.uniform(-0.3, 0.3)))
        movimiento = int(self.ventana % CICLO_MOVIMIENTO_S < CICLO_ACTIVO_S)

        # Votos: con movimiento, cada fuente vota verdadero con alta probabilidad.
        p = 0.8 if movimiento else 0.05
        votos = {f: int(r.random() < p) for f in FUENTES}
        n_true = sum(votos.values())
        activo = quorum_activo(self.rutas.control)
        alerta = int(n_true >= 2 and activo)

        ts = ahora.isoformat(timespec="seconds")
        foto = ""
        fuente_foto = None
        if alerta:
            fuente_foto = next(f for f in FUENTES if votos[f])
            identidad = r.choice(IDENTIDADES)
            foto = f"{fuente_foto}_{ahora.strftime('%Y%m%d_%H%M%S_%f')[:-3]}.jpg"
            (self.rutas.snapshots / foto).write_bytes(
                imagen_sintetica(fuente_foto, identidad, ahora)
            )
            self.reconocimientos.agregar(
                {
                    "ts_wall": ts,
                    "fuente": fuente_foto,
                    "ventana_ref": self.ventana,
                    "identidad": identidad,
                    "distancia": ""
                    if identidad == "desconocido"
                    else f"{r.uniform(0.25, 0.55):.4f}",
                    "snapshot": foto,
                }
            )
        trama = bytes(7)
        self.telemetria.agregar(
            {
                "timestamp": ts,
                "temperatura_c": f"{self.temp:.2f}",
                "humedad_pct": f"{self.hum:.2f}",
                "suelo_adc": "",
                "movimiento": movimiento,
                "foto": foto if movimiento else "",
                "trama_hex": trama.hex(" "),
            }
        )
        self.eventos.agregar(
            {
                "run_id": self.run_id,
                "ts_wall": ts,
                "ventana": self.ventana,
                "t_ventana_ini_ns": time.perf_counter_ns(),
                **{f"voto_{f}": votos[f] for f in FUENTES},
                **{f"bandera_{f}": votos[f] for f in FUENTES},
                "Q": round(n_true / len(FUENTES), 3),
                "n_true": n_true,
                "alerta": alerta,
                "marca": "" if activo else MARCA_DESACTIVADO,
            }
        )
        self.publicar_vivo(ahora)
        self.publicar_estado(ahora)
        return {
            "ventana": self.ventana,
            "movimiento": movimiento,
            "alerta": alerta,
            "foto": foto,
        }

    def publicar_vivo(self, ahora: datetime) -> None:
        """Un fotograma sintético por fuente hacia el visor (si no está, se ignora)."""
        for f in FUENTES:
            publicar_una_vez(f, imagen_sintetica(f, "", ahora))

    def publicar_estado(self, ahora: datetime) -> None:
        marca = ahora.isoformat(timespec="milliseconds")
        estado = {}
        for c in COMPONENTES:
            es_camara = c.startswith("camara_")
            fps = round(self.rng.uniform(8, 10), 1) if c == "camara_esp32" else None
            if c in ("camara_droidcam", "camara_local"):
                fps = round(self.rng.uniform(25, 30), 1)
            if c == "servicio_rostros":
                fps = round(self.rng.uniform(2, 5), 1)
            estado[c] = entrada(
                True, fps if (es_camara or c == "servicio_rostros") else None, marca
            )
        escribir_estado(self.rutas.estado, estado)


def correr(
    rutas: Rutas, hz: float = 1.0, pasos: int | None = None, semilla: int | None = None
) -> None:
    sim = Simulador(rutas, semilla, run_id=datetime.now().strftime("sim-%Y%m%d-%H%M%S"))
    n = 0
    try:
        while pasos is None or n < pasos:
            t0 = time.monotonic()
            sim.paso()
            n += 1
            time.sleep(max(0.0, 1 / hz - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        pass
