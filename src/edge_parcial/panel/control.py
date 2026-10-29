"""control.json: órdenes del panel al núcleo (escritor único: el panel).

    {"quorum_activo": true, "actualizado": "<ISO 8601>"}

Escritura atómica (temporal + `os.replace`); el núcleo lo lee al cerrar cada ventana. Un archivo
ausente, ilegible o sin la clave equivale a «quórum activo» (el valor seguro por defecto).
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

MARCA_DESACTIVADO = "quorum_desactivado"


def quorum_activo(ruta: Path | str | None) -> bool:
    if ruta is None:
        return True
    try:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return True
    return (
        datos.get("quorum_activo", True) is not False
        if isinstance(datos, dict)
        else True
    )


def escribir_quorum_activo(ruta: Path | str, activo: bool) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=".control-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "quorum_activo": bool(activo),
                    "actualizado": datetime.now()
                    .astimezone()
                    .isoformat(timespec="seconds"),
                },
                f,
            )
        os.replace(tmp, ruta)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
