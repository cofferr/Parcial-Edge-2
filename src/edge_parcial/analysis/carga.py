"""Carga de corridas desde data/raw (metadata.json + frames.csv)."""

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# Columnas enteras con posibles vacíos: Int64 anulable. Un float64 perdería precisión
# en las marcas en ns (> 2**53).
COLUMNAS_ENTERAS = [
    "seq", "warmup", "conexion", "t_request_ns", "t_first_ns", "t_last_ns",
    "t_decode_ini_ns", "t_ready_ns", "t_encode_ini_ns", "t_encode_fin_ns", "n_recv",
    "payload_bytes", "header_bytes", "raw_bytes", "jpeg_valid", "width", "height",
    "capture_us", "flush_us", "jpeg_us", "rssi_dbm", "bytes_recv_total", "descartado",
]  # fmt: skip


@dataclass
class Corrida:
    run_id: str
    ruta: Path
    meta: dict
    frames: pd.DataFrame
    extras: dict = field(default_factory=dict)

    @property
    def contexto(self) -> dict:
        return self.meta.get("contexto", {})

    @property
    def tarea(self) -> str | None:
        return self.contexto.get("tarea")

    @property
    def modo(self) -> str | None:
        return self.contexto.get("modo")

    @property
    def numero(self) -> int | None:
        return self.contexto.get("corrida")

    @property
    def fuentes(self) -> list[str]:
        return list(self.meta.get("fuentes_usadas", []))


def leer_frames(ruta: Path | str) -> pd.DataFrame:
    dtypes = {c: "Int64" for c in COLUMNAS_ENTERAS}
    return pd.read_csv(ruta, dtype=dtypes, keep_default_na=True)


def cargar_corridas(raw: Path | str, tarea: str | None = None) -> list[Corrida]:
    """Descubre las corridas de `raw` (con metadata.json y frames.csv), ordenadas por run_id."""
    corridas = []
    for meta_ruta in sorted(Path(raw).glob("*/metadata.json")):
        meta = json.loads(meta_ruta.read_text(encoding="utf-8"))
        if tarea is not None and meta.get("contexto", {}).get("tarea") != tarea:
            continue
        frames_ruta = meta_ruta.parent / "frames.csv"
        if not frames_ruta.is_file():
            continue
        corridas.append(
            Corrida(meta["run_id"], meta_ruta.parent, meta, leer_frames(frames_ruta))
        )
    return corridas
