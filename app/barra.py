"""Barra lateral: arranque de componentes, conexión y IP de las cámaras."""

import streamlit as st

from edge_parcial.config import ErrorConfig
from edge_parcial.panel import arranque
from edge_parcial.panel.ajustes import guardar_ips, leer_ips
from edge_parcial.panel.consultas import estado_componentes
from edge_parcial.panel.datos import rutas_por_defecto

ETIQUETAS = {
    "ble": "BLE",
    "servicio_rostros": "Servicio de rostros",
    "nucleo": "Núcleo",
    "camara_esp32": "ESP32-CAM",
    "camara_droidcam": "DroidCam",
    "camara_local": "Cámara local",
}
ORDEN = tuple(ETIQUETAS)
INDICADOR = {"vivo": "🟢", "sin señal": "🔴", "sin datos": "⚪"}


def _edad(s: float | None) -> str:
    if s is None:
        return "—"
    return f"hace {s:.0f} s" if s < 120 else f"hace {s / 60:.0f} min"


def _componentes(caidos: dict[str, int]) -> None:
    # Un proceso hijo caído se muestra aunque su último latido siga siendo reciente.
    caido_de = {
        arranque.COMPONENTE_DE[n]: c
        for n, c in caidos.items()
        if n in arranque.COMPONENTE_DE
    }
    vistas = {v.nombre: v for v in estado_componentes(rutas_por_defecto().estado)}
    for nombre in ORDEN:
        v = vistas[nombre]
        estado = v.estado
        if nombre in caido_de or (
            nombre.startswith("camara_") and "nucleo" in caido_de
        ):
            estado = "sin señal"
        st.markdown(f"{INDICADOR[estado]} **{ETIQUETAS[nombre]}** · {_edad(v.edad_s)}")
        if nombre in caido_de:
            st.caption(f"proceso caído (código {caido_de[nombre]})")
        elif v.errores:
            st.caption(f"último error: {v.errores[-1]}")


@st.fragment(run_every=1)
def _conexion() -> None:
    gestor = arranque.obtener()
    _componentes(gestor.caidos())


def _control(gestor: arranque.Arranque) -> None:
    if arranque.orquestado_externamente():
        st.caption("Componentes lanzados por scripts/demo.py.")
        return
    if not gestor.dueno:
        st.caption("Otro servidor del panel gestiona los componentes.")
        return
    o = gestor.opciones
    simular = st.checkbox("Simular datos", value=o.simular)
    sin_ble = st.checkbox("Sin BLE", value=o.sin_ble)
    sin_rostros = st.checkbox("Sin rostros", value=o.sin_rostros)
    sin_nucleo = st.checkbox("Sin núcleo", value=o.sin_nucleo)
    if st.button("Reiniciar componentes"):
        gestor.reiniciar(arranque.Opciones(simular, sin_ble, sin_rostros, sin_nucleo))
        st.rerun()


def _ips() -> None:
    with st.expander("IP de las cámaras"):
        actuales = leer_ips()
        with st.form("ips"):
            ip_esp32 = st.text_input("ESP32-CAM", value=actuales["esp32"])
            ip_droidcam = st.text_input("DroidCam", value=actuales["droidcam"])
            if st.form_submit_button("Guardar"):
                try:
                    guardar_ips(ip_esp32, ip_droidcam)
                    st.success("Guardado. Pulsa «Reiniciar componentes».")
                except ErrorConfig as e:
                    st.error(str(e))


def dibujar() -> None:
    with st.sidebar:
        if not arranque.orquestado_externamente():
            arranque.obtener().iniciar()  # una sola vez; si otro servidor es dueño, no hace nada
        st.subheader("Conexión")
        _conexion()
        st.divider()
        _control(arranque.obtener())
        _ips()
