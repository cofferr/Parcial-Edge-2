"""Página "Mediciones": tablas CSV y figuras de data/processed (Partes 1 a 3)."""

import pandas as pd
import streamlit as st

from edge_parcial.panel.consultas import figuras_disponibles, tablas_disponibles
from edge_parcial.panel.datos import rutas_por_defecto

st.title("Mediciones")
rutas = rutas_por_defecto()
tablas = tablas_disponibles(rutas)
figuras = figuras_disponibles(rutas)

if not tablas and not figuras:
    st.info(
        f"Sin resultados procesados en {rutas.figuras}. "
        "Ejecuta los análisis de las partes para generar tablas y figuras."
    )

for parte in sorted({*tablas, *figuras}, key=lambda p: (p == "Otras", p)):
    st.header(parte)
    for ruta in tablas.get(parte, []):
        with st.expander(ruta.stem):
            try:
                st.dataframe(pd.read_csv(ruta), width="stretch")
            except (
                pd.errors.ParserError,
                pd.errors.EmptyDataError,
                UnicodeDecodeError,
            ) as e:
                st.warning(f"No se pudo leer {ruta.name}: {e}")
    for ruta in figuras.get(parte, []):
        st.image(str(ruta), caption=ruta.stem)
