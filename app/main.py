"""Panel. Lanzar con: uv run streamlit run app/main.py (lanza también los componentes)."""

import sys
from pathlib import Path

import streamlit as st

AQUI = Path(__file__).parent
sys.path.insert(0, str(AQUI))  # para importar barra.py

import barra

st.set_page_config(page_title="Edge parcial", layout="wide")
barra.dibujar()
pagina = st.navigation(
    [
        st.Page(AQUI / "paginas" / "vivo.py", title="Vivo", default=True),
        st.Page(AQUI / "paginas" / "camaras.py", title="Cámaras"),
        st.Page(AQUI / "paginas" / "datos.py", title="Datos"),
        st.Page(AQUI / "paginas" / "registro.py", title="Registro"),
        st.Page(AQUI / "paginas" / "mediciones.py", title="Mediciones"),
    ]
)
pagina.run()
