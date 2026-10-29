"""Página "Registro": alta de rostros conocidos (foto de la cámara local o imagen subida)."""

import streamlit as st

from edge_parcial.rostros import registro
from edge_parcial.visor.cliente import obtener_ultimo
from edge_parcial.visor.servidor import HOST, PUERTO

st.title("Registro de rostros")
st.caption(
    "Los datos faciales se guardan en rostros_conocidos/ (fuera de git). "
    "El servicio de rostros los recarga solo, sin reiniciar."
)

nombre = st.text_input("Nombre de la persona")
col_cam, col_subir = st.columns(2)

with col_cam:
    st.subheader("Cámara local")
    st.html(
        f'<img src="http://{HOST}:{PUERTO}/stream/local" alt="cámara local" '
        'style="width:100%;border-radius:6px;background:#222">'
    )
    tomar = st.button("Tomar muestra de la cámara local")
with col_subir:
    st.subheader("Subir imagen")
    archivo = st.file_uploader("JPG o PNG", type=["jpg", "jpeg", "png"])
    subir = st.button("Guardar imagen subida", disabled=archivo is None)

datos: bytes | None = None
if tomar:
    datos = obtener_ultimo("local", max_edad_s=2.0)
    if datos is None:
        st.error(
            "Sin fotograma reciente de la cámara local (¿está corriendo el núcleo?)."
        )
elif subir and archivo is not None:
    datos = archivo.getvalue()

if datos is not None:
    try:
        ruta = registro.agregar_muestra(nombre, datos)
        st.success(f"Muestra guardada: {ruta.parent.name}/{ruta.name}")
    except registro.ErrorRegistro as e:
        st.error(str(e))

st.subheader("Personas registradas")
personas = registro.listar()
if not personas:
    st.info("Todavía no hay personas registradas.")
for persona, n in personas.items():
    c1, c2 = st.columns([4, 1])
    c1.markdown(f"**{persona}** · {n} {'muestra' if n == 1 else 'muestras'}")
    if c2.button("Archivar", key=f"archivar_{persona}", help="Se conserva en _archivo"):
        registro.archivar(persona)
        st.rerun()
