"""Página "Datos": telemetria.csv, eventos.csv y reconocimientos.csv (solo lectura)."""

import streamlit as st

from edge_parcial.panel.consultas import (
    filtrar_eventos,
    filtrar_reconocimientos,
    telemetria_reciente,
    valores_distintos,
)
from edge_parcial.panel.datos import FUENTES, leer_csv, rutas_por_defecto

st.title("Datos")
c1, c2 = st.columns([1, 3])
n = c1.number_input("Últimas N filas", min_value=10, max_value=2000, value=100, step=10)
refrescar = c2.toggle("Refrescar cada 2 s", value=True)


def _tablas(n: int) -> None:
    rutas = rutas_por_defecto()
    tab_tel, tab_ev, tab_rec = st.tabs(["Telemetría", "Eventos", "Reconocimientos"])

    with tab_tel:
        tel = telemetria_reciente(rutas, n)
        if tel.empty:
            st.info("Sin lecturas en telemetria.csv.")
        else:
            g1, g2 = st.columns(2)
            g1.caption("Temperatura (°C)")
            g1.line_chart(tel["temperatura_c"], height=200)
            g2.caption("Humedad (%)")
            g2.line_chart(tel["humedad_pct"], height=200)
            st.dataframe(tel.drop(columns=["trama_hex"]).iloc[::-1], width="stretch")

    with tab_ev:
        ev = leer_csv(rutas.eventos, ultimas=n)
        if ev.empty:
            st.info("Sin ventanas en eventos.csv.")
        else:
            f1, f2, f3 = st.columns(3)
            fuente = f1.selectbox(
                "Votó la fuente", ["todas", *FUENTES], key="ev_fuente"
            )
            marcas = ["todas", "(sin marca)", *valores_distintos(ev, "marca")]
            marca = f2.selectbox("Marca", marcas, key="ev_marca")
            solo = f3.checkbox("Solo alertas", key="ev_alertas")
            vista = filtrar_eventos(ev, fuente, solo, marca)
            st.caption(f"{len(vista)} de {len(ev)} ventanas")
            st.dataframe(vista.iloc[::-1], width="stretch")

    with tab_rec:
        rec = leer_csv(rutas.reconocimientos, ultimas=n)
        if rec.empty:
            st.info("Sin reconocimientos en reconocimientos.csv.")
        else:
            r1, r2 = st.columns(2)
            fuente = r1.selectbox("Fuente", ["todas", *FUENTES], key="rec_fuente")
            identidad = r2.selectbox(
                "Identidad",
                ["todas", *valores_distintos(rec, "identidad")],
                key="rec_id",
            )
            vista = filtrar_reconocimientos(rec, fuente, identidad)
            st.caption(f"{len(vista)} de {len(rec)} reconocimientos")
            st.dataframe(vista.iloc[::-1], width="stretch")


if refrescar:
    st.fragment(_tablas, run_every=2)(int(n))
else:
    _tablas(int(n))
