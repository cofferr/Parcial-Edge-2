"""Escritura de tablas: CSV con valores sin redondear y LaTeX redondeado solo al presentar."""

import math
from pathlib import Path

import pandas as pd

_ESCAPES = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}"}  # fmt: skip


def escapar(texto: str) -> str:
    return "".join(_ESCAPES.get(c, c) for c in str(texto))


def formatear(valor, decimales: int) -> str:
    """Celda LaTeX: redondea solo aquí; NaN/None -> '--'."""
    if (
        valor is None
        or (isinstance(valor, float) and math.isnan(valor))
        or valor is pd.NA
    ):
        return "--"
    if isinstance(valor, bool):
        return "sí" if valor else "no"
    if isinstance(valor, int) or (
        hasattr(valor, "dtype") and "int" in str(valor.dtype)
    ):
        return str(int(valor))
    if isinstance(valor, float):
        return f"{valor:.{decimales}f}"
    return escapar(valor)


def a_latex(
    df: pd.DataFrame,
    caption: str,
    label: str,
    decimales: dict | int = 2,
    titulos: dict | None = None,
) -> str:
    titulos = titulos or {}
    cols = list(df.columns)
    alin = "".join("l" if df[c].dtype == object else "r" for c in cols)
    cab = " & ".join(escapar(titulos.get(c, c)) for c in cols)
    lineas = [
        r"\begin{table}[htbp]",
        r"\centering",
        rf"\caption{{{escapar(caption)}}}",
        rf"\label{{{label}}}",
        r"\small",
        rf"\begin{{tabular}}{{{alin}}}",
        r"\toprule",
        cab + r" \\",
        r"\midrule",
    ]
    for _, fila in df.iterrows():
        celdas = []
        for c in cols:
            d = decimales.get(c, 2) if isinstance(decimales, dict) else decimales
            celdas.append(formatear(fila[c], d))
        lineas.append(" & ".join(celdas) + r" \\")
    lineas += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    return "\n".join(lineas)


def escribir_tabla(
    df: pd.DataFrame,
    base: Path | str,
    *,
    caption: str,
    label: str,
    decimales: dict | int = 2,
    titulos: dict | None = None,
) -> tuple[Path, Path]:
    """Escribe `<base>.csv` (valores completos) y `<base>.tex` (redondeado)."""
    base = Path(base)
    base.parent.mkdir(parents=True, exist_ok=True)
    ruta_csv = base.with_suffix(".csv")
    ruta_tex = base.with_suffix(".tex")
    df.to_csv(ruta_csv, index=False)  # float -> repr completo, sin redondear
    ruta_tex.write_text(
        a_latex(df, caption, label, decimales, titulos), encoding="utf-8"
    )
    return ruta_csv, ruta_tex
