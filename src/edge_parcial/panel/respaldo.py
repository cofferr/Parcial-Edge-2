"""Copia de seguridad previa al arranque: data/*.csv y rostros_conocidos/ -> data/_respaldo/<fecha>/.

Solo copia (nunca mueve ni borra) y conserva todas las copias. Restaurar: ver
`scripts/restaurar_respaldo.py`.
"""

import logging
import shutil
from datetime import datetime
from pathlib import Path

from edge_parcial.csv_anexar import ruta_libre

log = logging.getLogger("edge_parcial.respaldo")
CARPETA = "_respaldo"
SUBCARPETA_ROSTROS = "rostros_conocidos"


def respaldar(
    base: Path | str, rostros: Path | str | None = None, ahora: datetime | None = None
) -> Path | None:
    """Devuelve la carpeta de la copia, o None si no había nada que copiar."""
    base = Path(base)
    csvs = sorted(base.glob("*.csv")) if base.is_dir() else []
    hay_rostros = rostros is not None and Path(rostros).is_dir()
    if not csvs and not hay_rostros:
        return None
    marca = (ahora or datetime.now()).strftime("%Y%m%d-%H%M%S")
    destino = ruta_libre(base / CARPETA / marca)
    destino.mkdir(parents=True)
    for f in csvs:
        shutil.copy2(f, destino / f.name)
    if hay_rostros:
        shutil.copytree(Path(rostros), destino / SUBCARPETA_ROSTROS)
    log.info("Respaldo en %s", destino)
    return destino
