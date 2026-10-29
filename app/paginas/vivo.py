"""Página "Vivo": estado de componentes, telemetría, ventanas y evidencias."""

import streamlit as st

from edge_parcial.ble.gateway import ParamsBle
from edge_parcial.panel.consultas import (
    estado_componentes,
    evidencias,
    telemetria_reciente,
    ventanas_recientes,
)
from edge_parcial.panel.datos import rutas_por_defecto

REFRESCO_S = 1


def _estado(rutas) -> None:
    st.subheader("Componentes")
    vistas = estado_componentes(rutas.estado)
    columnas = st.columns(len(vistas))
    for col, v in zip(columnas, vistas, strict=True):
        with col:
            simbolo = {"vivo": "●", "sin señal": "○", "sin datos": "·"}[v.estado]
            st.markdown(f"**{v.nombre}**  \n{simbolo} {v.estado}")
            if v.nombre == "ble":
                st.caption(f"estación: {ParamsBle().nombre}")
            if v.fps is not None:
                st.caption(f"{v.fps} fps")
            st.caption(f"última: {v.ultima_marca}")
            if v.errores:
                with st.expander(f"{len(v.errores)} errores"):
                    st.text("\n".join(v.errores))
    if all(v.estado == "sin datos" for v in vistas):
        st.info("Sin estado.json todavía: ningún componente ha publicado su latido.")


def _telemetria(rutas) -> None:
    st.subheader("Telemetría")
    tel = telemetria_reciente(rutas)
    if tel.empty:
        st.info("Sin lecturas en telemetria.csv.")
        return
    ultima = tel.iloc[-1]
    c1, c2, c3 = st.columns(3)
    c1.metric("Temperatura", f"{ultima['temperatura_c']:.1f} °C")
    c2.metric("Humedad", f"{ultima['humedad_pct']:.1f} %")
    c3.metric("PIR", "movimiento" if ultima["movimiento"] == 1 else "quieto")
    g1, g2, g3 = st.columns(3)
    g1.caption("Temperatura (°C)")
    g1.line_chart(tel["temperatura_c"], height=180)
    g2.caption("Humedad (%)")
    g2.line_chart(tel["humedad_pct"], height=180)
    g3.caption("PIR (1 = movimiento)")
    g3.bar_chart(tel["movimiento"], height=180)
    with st.expander("Últimas lecturas"):
        mostrar = tel.drop(columns=["trama_hex"]).iloc[::-1].head(15)
        st.dataframe(mostrar, width="stretch")


def _ventanas(rutas) -> None:
    st.subheader("Últimas ventanas")
    tabla = ventanas_recientes(rutas)
    if tabla.empty:
        st.info("Sin ventanas en eventos.csv (el núcleo aún no ha escrito).")
        return

    def color(v):
        return (
            "background-color: #d62728; color: white" if v else "background-color: #eee"
        )

    simbolos = tabla.map(lambda v: "●" if v else "·")
    estilo = simbolos.style.apply(
        lambda s: [color(tabla.loc[s.name, c]) for c in s.index], axis=1
    )
    st.dataframe(estilo, width="stretch")
    st.caption("Filas: voto de cada fuente y alerta. Columnas: número de ventana.")


def _galeria(rutas) -> None:
    st.subheader("Evidencias")
    items = evidencias(rutas)
    if not items:
        st.info("Sin evidencias: no hay reconocimientos con imagen en snapshots.")
        return
    columnas = st.columns(4)
    for i, ev in enumerate(items):
        with columnas[i % 4]:
            st.image(str(ev.ruta), width="stretch")
            dist = f" (d={ev.distancia})" if ev.distancia else ""
            st.caption(f"**{ev.identidad}**{dist} · {ev.fuente} · {ev.ts_wall}")


@st.fragment(run_every=REFRESCO_S)
def _contenido() -> None:
    rutas = rutas_por_defecto()
    _estado(rutas)
    _telemetria(rutas)
    _ventanas(rutas)
    _galeria(rutas)


st.title("Vivo")
_contenido()
