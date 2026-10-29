"""Página "Cámaras": últimos fotogramas que escribe el núcleo (el panel no toca las cámaras)."""

import streamlit as st

from edge_parcial.panel.consultas import estado_por_fuente, fotograma_vivo
from edge_parcial.panel.datos import FUENTES, rutas_por_defecto

REFRESCO_S = 0.5
ETIQUETA = {"esp32": "ESP32-CAM", "droidcam": "DroidCam", "local": "Cámara local"}
ICONO = {"movimiento": "🔴", "quieto": "⚪", "tapada": "⚫", "sin_datos": "❔"}


def _una(rutas, fuente: str, estados) -> None:
    e = estados[fuente]
    voto = {True: "voto: sí", False: "voto: no", None: "voto: —"}[e.voto]
    st.markdown(f"**{ETIQUETA[fuente]}** · {ICONO[e.estado]} {e.estado} · {voto}")
    datos = fotograma_vivo(rutas, fuente)
    if datos is None:
        st.info("sin señal")
    else:
        st.image(datos, width="stretch")


@st.fragment(run_every=REFRESCO_S)
def _visor(modo: str, elegida: str) -> None:
    rutas = rutas_por_defecto()
    estados, alerta = estado_por_fuente(rutas)
    if alerta:
        st.error("ALERTA: quórum alcanzado en la última ventana")
    if modo == "Una cámara":
        _una(rutas, elegida, estados)
        return
    for col, fuente in zip(st.columns(len(FUENTES)), FUENTES, strict=True):
        with col:
            _una(rutas, fuente, estados)


st.title("Cámaras")
modo = st.radio("Vista", ["Las tres", "Una cámara"], horizontal=True)
elegida = FUENTES[0]
if modo == "Una cámara":
    elegida = st.selectbox("Cámara", FUENTES, format_func=ETIQUETA.get)
_visor(modo, elegida)
