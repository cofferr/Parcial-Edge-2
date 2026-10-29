"""Página "Cámaras": MJPEG que sirve el visor (el panel no abre las cámaras ni lee JPEG de disco)."""

import streamlit as st

from edge_parcial.panel.consultas import estado_por_fuente
from edge_parcial.panel.control import quorum_activo
from edge_parcial.panel.datos import FUENTES, rutas_por_defecto
from edge_parcial.visor.servidor import HOST, PUERTO

ETIQUETA = {"esp32": "ESP32-CAM", "droidcam": "DroidCam", "local": "Cámara local"}
ICONO = {"movimiento": "🔴", "quieto": "⚪", "tapada": "⚫", "sin_datos": "❔"}


def _img(fuente: str) -> None:
    # El navegador abre el flujo directamente (127.0.0.1); Streamlit solo incrusta la URL.
    st.html(
        f'<img src="http://{HOST}:{PUERTO}/stream/{fuente}" alt="{ETIQUETA[fuente]}" '
        'style="width:100%;border-radius:6px;background:#222">'
    )


@st.fragment(run_every=1)
def _leyenda(fuente: str) -> None:
    estados, _ = estado_por_fuente(rutas_por_defecto())
    e = estados[fuente]
    voto = {True: "voto: sí", False: "voto: no", None: "voto: —"}[e.voto]
    st.markdown(f"**{ETIQUETA[fuente]}** · {ICONO[e.estado]} {e.estado} · {voto}")


@st.fragment(run_every=1)
def _alerta() -> None:
    rutas = rutas_por_defecto()
    _, alerta = estado_por_fuente(rutas)
    if not quorum_activo(rutas.control):
        st.warning("Quórum desactivado: sin alertas ni reconocimiento")
    elif alerta:
        st.error("ALERTA: quórum alcanzado en la última ventana")


st.title("Cámaras")
modo = st.radio("Vista", ["Las tres", "Una cámara"], horizontal=True)
_alerta()
if modo == "Una cámara":
    elegida = st.selectbox("Cámara", FUENTES, format_func=ETIQUETA.get)
    _leyenda(elegida)
    _img(elegida)
else:
    for col, fuente in zip(st.columns(len(FUENTES)), FUENTES, strict=True):
        with col:
            _leyenda(fuente)
            _img(fuente)
