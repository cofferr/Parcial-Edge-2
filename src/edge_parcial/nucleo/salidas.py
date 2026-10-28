"""Salidas del núcleo según docs/CONTRATO_DATOS.md: eventos.csv, estado.json y log de consola.

- eventos.csv: solo de añadir, una fila por ventana, `flush` por fila, cabecera una vez.
  Los votos y `alerta` se escriben como 1/0.
- estado.json: latido atómico (archivo temporal en la misma carpeta + `os.replace`).
"""

import csv
import json
import os
import threading
from datetime import datetime
from pathlib import Path

from edge_parcial.nucleo.modelo import Decision

FUENTES = ("esp32", "droidcam", "local")
COLUMNAS_EVENTOS = [
    "run_id", "ts_wall", "ventana", "t_ventana_ini_ns",
    *[f"voto_{f}" for f in FUENTES],
    *[f"bandera_{f}" for f in FUENTES],
    "Q", "n_true", "alerta",
]  # fmt: skip
COMPONENTES_ESTADO = (
    "camara_esp32", "camara_droidcam", "camara_local", "ble", "servicio_rostros", "nucleo",
)  # fmt: skip


class ErrorEsquema(Exception):
    """El eventos.csv existente tiene otra cabecera."""


class EventosCSV:
    """Escritor único de eventos.csv (solo añade; nunca reescribe filas)."""

    def __init__(self, ruta: Path | str, run_id: str) -> None:
        self.ruta = Path(ruta)
        self.run_id = run_id
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        nuevo = not self.ruta.exists() or self.ruta.stat().st_size == 0
        if not nuevo:
            with open(self.ruta, encoding="utf-8", newline="") as f:
                cab = next(csv.reader(f), [])
            if cab != COLUMNAS_EVENTOS:
                raise ErrorEsquema(
                    f"{self.ruta} tiene una cabecera distinta del contrato"
                )
        self._f = open(self.ruta, "a", encoding="utf-8", newline="")  # noqa: SIM115 - queda abierto
        self._w = csv.DictWriter(self._f, COLUMNAS_EVENTOS, lineterminator="\n")
        if nuevo:
            self._w.writeheader()
            self._f.flush()
        self._lock = threading.Lock()

    def escribir(self, d: Decision) -> None:
        fila = {
            "run_id": self.run_id, "ts_wall": d.ts_wall, "ventana": d.ventana,
            "t_ventana_ini_ns": d.t_ini_ns, "Q": d.q, "n_true": d.n_true,
            "alerta": int(d.alerta),
        }  # fmt: skip
        for f in FUENTES:
            v = d.votos.get(f)
            fila[f"voto_{f}"] = "" if v is None else int(v.voto)
            fila[f"bandera_{f}"] = "" if v is None else v.bandera
        with self._lock:
            # Una sola llamada de escritura por fila y flush: nunca queda una fila a medias.
            self._w.writerow(fila)
            self._f.flush()

    def cerrar(self) -> None:
        with self._lock:
            self._f.close()


def linea_log(d: Decision, fuentes: tuple[str, ...] = FUENTES) -> str:
    """Una línea por ventana, legible en una captura de pantalla."""
    partes = []
    for f in fuentes:
        v = d.votos[f]
        partes.append(f"{f} {'SI' if v.voto else 'no'} ({v.bandera})")
    hora = d.ts_wall[11:23]
    cola = f"votos {d.n_true}/{len(fuentes)} Q={d.q}"
    return (
        f"[{hora}] ventana {d.ventana:04d} | "
        + " | ".join(partes)
        + f" | {cola}"
        + (" | >>> ALERTA <<<" if d.alerta else "")
    )


def escribir_atomico(ruta: Path | str, datos: dict) -> None:
    """Escribe JSON en un temporal de la misma carpeta y lo renombra sobre `ruta`."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(f".{ruta.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ruta)


def entrada_estado(vivo: bool, fps=None, ultima_marca=None, errores=None) -> dict:
    return {
        "vivo": bool(vivo),
        "fps": fps,
        "ultima_marca": ultima_marca,
        "errores_recientes": list(errores or []),
    }


def estado_completo(camaras: dict[str, dict], nucleo: dict) -> dict:
    """Las seis claves fijas del contrato. `ble` y `servicio_rostros` no son del núcleo."""
    # `ble` y `servicio_rostros` no los conoce el núcleo: se declaran no reportados.
    estado = {
        c: entrada_estado(False, errores=["no reportado por el núcleo"])
        for c in COMPONENTES_ESTADO
    }
    for fuente, e in camaras.items():
        estado[f"camara_{fuente}"] = e
    estado["nucleo"] = nucleo
    return estado


def ahora_iso() -> str:
    return datetime.now().astimezone().isoformat()
