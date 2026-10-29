"""Página "Datos": telemetria.csv, eventos.csv y reconocimientos.csv (solo lectura)."""

import pandas as pd
import streamlit as st

from edge_parcial.panel.consultas import (
    filtrar_eventos,
    filtrar_reconocimientos,
    preparar_telemetria,
    valores_distintos,
)
from edge_parcial.panel.datos import FUENTES, rutas_por_defecto
from edge_parcial.panel.historico import filtrar, leer_historico, resumen, sesiones

st.title("Datos")
c1, c2, c3 = st.columns([1, 2, 2])
n = c1.number_input("Últimas N filas", min_value=10, max_value=5000, value=100, step=10)
alcance = c2.radio(
    "Alcance",
    ["Todas las sesiones", "Una sesión", "Histórico completo"],
    help="Todas: archivos actuales. Una sesión: elige cuál. Histórico: incluye también "
    "los archivos apartados al cambiar el esquema.",
)
rango = c3.date_input("Rango de fechas (opcional)", value=(), format="YYYY-MM-DD")
refrescar = st.toggle("Refrescar cada 2 s", value=True)
desde = rango[0] if len(rango) >= 1 else None
hasta = rango[1] if len(rango) == 2 else desde


def _cargar(ruta, columna_ts: str, sesion: str | None):
    """(vista filtrada, total de filas del alcance, desde cuándo hay datos)."""
    df = leer_historico(ruta, incluir_apartados=alcance != "Todas las sesiones")
    vista = filtrar(df, columna_ts, sesion, desde, hasta)
    total, inicio = resumen(df, columna_ts)
    return vista, total, inicio


def _resumen(vista, total: int, inicio: str) -> None:
    st.caption(
        f"{len(vista)} filas en el filtro · {total} en el alcance · datos desde {inicio}"
    )


def _tablas(n: int) -> None:
    rutas = rutas_por_defecto()
    sesion = None
    if alcance == "Una sesión":
        todas = sesiones(
            pd.concat(
                [
                    leer_historico(rutas.telemetria, True),
                    leer_historico(rutas.eventos, True),
                    leer_historico(rutas.reconocimientos, True),
                ],
                ignore_index=True,
                sort=False,
            )
        )
        if not todas:
            st.info("Todavía no hay sesiones registradas.")
            return
        sesion = st.selectbox("Sesión", todas, key="sesion_elegida")
    tab_tel, tab_ev, tab_rec = st.tabs(["Telemetría", "Eventos", "Reconocimientos"])

    with tab_tel:
        vista, total, inicio = _cargar(rutas.telemetria, "timestamp", sesion)
        if vista.empty:
            st.info("Sin lecturas de telemetría para este filtro.")
        else:
            _resumen(vista, total, inicio)
            tel = preparar_telemetria(vista.tail(n))
            g1, g2 = st.columns(2)
            g1.caption("Temperatura (°C)")
            g1.line_chart(tel["temperatura_c"], height=200)
            g2.caption("Humedad (%)")
            g2.line_chart(tel["humedad_pct"], height=200)
            st.dataframe(tel.drop(columns=["trama_hex"]).iloc[::-1], width="stretch")

    with tab_ev:
        vista, total, inicio = _cargar(rutas.eventos, "ts_wall", sesion)
        if vista.empty:
            st.info("Sin ventanas en eventos para este filtro.")
        else:
            _resumen(vista, total, inicio)
            f1, f2, f3 = st.columns(3)
            fuente = f1.selectbox(
                "Votó la fuente", ["todas", *FUENTES], key="ev_fuente"
            )
            marcas = ["todas", "(sin marca)", *valores_distintos(vista, "marca")]
            marca = f2.selectbox("Marca", marcas, key="ev_marca")
            solo = f3.checkbox("Solo alertas", key="ev_alertas")
            vista = filtrar_eventos(vista, fuente, solo, marca).tail(n)
            st.caption(f"{len(vista)} ventanas mostradas")
            st.dataframe(vista.iloc[::-1], width="stretch")

    with tab_rec:
        vista, total, inicio = _cargar(rutas.reconocimientos, "ts_wall", sesion)
        if vista.empty:
            st.info("Sin reconocimientos para este filtro.")
        else:
            _resumen(vista, total, inicio)
            r1, r2 = st.columns(2)
            fuente = r1.selectbox("Fuente", ["todas", *FUENTES], key="rec_fuente")
            identidad = r2.selectbox(
                "Identidad",
                ["todas", *valores_distintos(vista, "identidad")],
                key="rec_id",
            )
            vista = filtrar_reconocimientos(vista, fuente, identidad).tail(n)
            st.caption(f"{len(vista)} reconocimientos mostrados")
            st.dataframe(vista.iloc[::-1], width="stretch")


if refrescar:
    st.fragment(_tablas, run_every=2)(int(n))
else:
    _tablas(int(n))
