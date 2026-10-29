"""Datos históricos de solo anexar: nada se borra ni se sobrescribe.

- `preparar_csv`: si el archivo existe con la misma cabecera se conserva y se sigue
  escribiendo; si la cabecera cambió, el archivo viejo se aparta con otro nombre (no se
  pierde) y se empieza uno nuevo.
- `ruta_libre`: un nombre que no existe todavía (nunca se pisa un archivo).
- `copia_con_fecha`: copia de seguridad previa a modificar un archivo de configuración.
"""

import csv
import shutil
from datetime import datetime
from pathlib import Path


def ruta_libre(ruta: Path | str) -> Path:
    """`ruta` si no existe; si no, `<nombre>_2<ext>`, `_3`, ... (nunca sobrescribe)."""
    ruta = Path(ruta)
    candidata, n = ruta, 2
    while candidata.exists():
        candidata = ruta.with_name(f"{ruta.stem}_{n}{ruta.suffix}")
        n += 1
    return candidata


def preparar_csv(ruta: Path | str, columnas: list[str]) -> bool:
    """Deja `ruta` lista para anexar. True = hay que escribir la cabecera (archivo nuevo)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if not ruta.exists() or ruta.stat().st_size == 0:
        return True
    with open(ruta, encoding="utf-8", newline="") as f:
        cabecera = next(csv.reader(f), [])
    if cabecera == columnas:
        with open(
            ruta, "rb+"
        ) as f:  # una fila a medias (caída) no debe pegarse a la nueva
            f.seek(-1, 2)
            if f.read(1) != b"\n":
                f.write(b"\n")
        return False
    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    ruta.rename(ruta_libre(ruta.with_name(f"{ruta.stem}.antes-{marca}{ruta.suffix}")))
    return True


def copia_con_fecha(ruta: Path | str) -> Path | None:
    """Copia `ruta` a `<ruta>.bak-<fecha>` (sin sobrescribir). None si no existe."""
    ruta = Path(ruta)
    if not ruta.is_file():
        return None
    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = ruta_libre(ruta.with_name(f"{ruta.name}.bak-{marca}"))
    shutil.copy2(ruta, destino)
    return destino
