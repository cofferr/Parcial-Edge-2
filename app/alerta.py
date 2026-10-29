"""Alerta visible en todas las páginas: se activa cuando el quórum se cumple."""

from html import escape

import streamlit as st

from edge_parcial.panel.consultas import alerta_activa
from edge_parcial.panel.datos import rutas_por_defecto

MANTENER_S = (
    10.0  # la alerta se queda en pantalla este tiempo tras la última ventana en alerta
)

ESTILO = """
<style>
.stApp { background: #3d0a0a !important; }
img[src*="/stream/"] { border: 6px solid #ff2d2d !important; }
@keyframes pulso { 0%,100% { box-shadow: 0 0 0 0 rgba(255,45,45,.8);} 50% { box-shadow: 0 0 40px 12px rgba(255,45,45,.9);} }
.banner-alerta { background:#d10000; color:#fff; border-radius:12px; padding:22px 28px;
  animation: pulso 1s infinite; margin-bottom:14px; }
.banner-alerta .titulo { font-size:2.1rem; font-weight:800; letter-spacing:.04em; }
.banner-alerta .nombre { font-size:3.2rem; font-weight:900; line-height:1.1; margin-top:6px; }
.banner-alerta .detalle { font-size:1rem; opacity:.9; margin-top:4px; }
</style>
"""


@st.fragment(run_every=1)
def dibujar() -> None:
    a = alerta_activa(rutas_por_defecto(), mantener_s=MANTENER_S)
    if a is None:
        return
    if a.estado == "identificado":
        quien = " · ".join(escape(n) for n in a.nombres)
    elif a.estado == "reconociendo":
        quien = "Identificando…"
    else:
        quien = "Sin rostro identificado"
    st.markdown(
        ESTILO
        + f'<div class="banner-alerta"><div class="titulo">🚨 ALERTA · QUÓRUM CUMPLIDO · {a.n_true} fuentes con movimiento</div>'
        f'<div class="nombre">{quien}</div>'
        f'<div class="detalle">Ventana #{a.ventana} · {a.ts_wall[:19].replace("T", " ")}</div></div>',
        unsafe_allow_html=True,
    )
    if a.snapshot is not None:
        st.image(str(a.snapshot), width=360)
