"""Panel de solo lectura. Lanzar con: uv run streamlit run app/main.py"""

from pathlib import Path

import streamlit as st

AQUI = Path(__file__).parent

st.set_page_config(page_title="Edge parcial", layout="wide")
pagina = st.navigation(
    [
        st.Page(AQUI / "paginas" / "vivo.py", title="Vivo", default=True),
        st.Page(AQUI / "paginas" / "mediciones.py", title="Mediciones"),
    ]
)
pagina.run()
