"""Página "Historial": ventanas del quórum con su marca de tiempo, alertas y quién fue reconocido."""

import pandas as pd
import streamlit as st

from edge_parcial.panel.consultas import unir_alertas
from edge_parcial.panel.datos import FUENTES, rutas_por_defecto
from edge_parcial.panel.historico import filtrar, leer_historico, resumen, sesiones

st.title("Historial")
c1, c2 = st.columns([2, 2])
alcance = c1.radio(
    "Alcance",
    ["Todas las sesiones", "Una sesión", "Histórico completo"],
    horizontal=True,
    key="hist_alcance",
)
rango = c2.date_input(
    "Rango de fechas (opcional)", value=(), format="YYYY-MM-DD", key="hist_rango"
)
desde = rango[0] if len(rango) >= 1 else None
hasta = rango[1] if len(rango) == 2 else desde
solo_alertas = st.checkbox("Solo ventanas con alerta", key="hist_solo")

rutas = rutas_por_defecto()
completo = alcance != "Todas las sesiones"
ev_todo = leer_historico(rutas.eventos, incluir_apartados=completo)
rec_todo = leer_historico(rutas.reconocimientos, incluir_apartados=completo)

sesion = None
if alcance == "Una sesión":
    opciones = sesiones(leer_historico(rutas.eventos, True))
    if not opciones:
        st.info("Todavía no hay sesiones registradas.")
        st.stop()
    sesion = st.selectbox("Sesión", opciones, key="hist_sesion")

ev = filtrar(ev_todo, "ts_wall", sesion, desde, hasta)
rec = filtrar(rec_todo, "ts_wall", sesion, desde, hasta)
if ev.empty:
    st.info("Sin ventanas en eventos para este filtro.")
    st.stop()

total, inicio = resumen(ev_todo, "ts_wall")
alertas = unir_alertas(ev, rec)
desconocidos = (
    int(alertas["reconocidos"].str.contains("DESCONOCIDO").sum()) if len(alertas) else 0
)
m1, m2, m3, m4 = st.columns(4)
m1.metric("Ventanas", len(ev))
m2.metric("Alertas", len(alertas))
m3.metric("Con desconocido", desconocidos)
m4.metric("Datos desde", inicio[:19])

# -- línea de tiempo: fuentes que votaron por ventana y alertas por minuto -----------------------
t = pd.to_datetime(ev["ts_wall"].astype(str).str.slice(0, 19), errors="coerce")
lin = pd.DataFrame({"n_true": pd.to_numeric(ev["n_true"], errors="coerce")}).set_index(
    t
)
lin = lin[lin.index.notna()]
g1, g2 = st.columns(2)
g1.caption("Fuentes con movimiento por ventana (n_true)")
g1.line_chart(lin["n_true"], height=200)
al = pd.to_numeric(ev["alerta"], errors="coerce").fillna(0).set_axis(t)
al = al[al.index.notna()]
g2.caption("Alertas por minuto")
g2.bar_chart(al.resample("1min").sum(), height=200, color="#d10000")

# -- alertas y quién fue reconocido ----------------------------------------------------------------
st.subheader("Alertas")
if alertas.empty:
    st.info("No hubo alertas en este filtro.")
else:
    st.dataframe(alertas.iloc[::-1].drop(columns=["snapshot"]), width="stretch")
    st.caption("Fotos de las alertas (más recientes primero)")
    fotos = alertas[alertas["snapshot"] != ""].iloc[::-1].head(12)
    columnas = st.columns(4)
    for i, f in enumerate(fotos.itertuples()):
        ruta = rutas.snapshots / f.snapshot
        if ruta.is_file():
            with columnas[i % 4]:
                st.image(str(ruta), width="stretch")
                st.caption(
                    f"**{f.reconocidos}** · {str(f.ts_wall)[:19].replace('T', ' ')} · #{f.ventana}"
                )

# -- todas las ventanas con su marca de tiempo --------------------------------------------------------
st.subheader("Todas las ventanas")
vista = ev[ev["alerta"].astype(str).isin(["1"])] if solo_alertas else ev
cols = [
    "ts_wall",
    "ventana",
    *[f"voto_{f}" for f in FUENTES],
    "n_true",
    "Q",
    "alerta",
    "marca",
    "session_id",
]
st.dataframe(vista[[c for c in cols if c in vista.columns]].iloc[::-1], width="stretch")
