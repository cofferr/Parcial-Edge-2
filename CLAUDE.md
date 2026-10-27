# edge-parcial

Parcial de Edge Computing, Parte 1 (latencia y ancho de banda). Lee `docs/DISENO.md` (decisiones cerradas, no reabrir) y `docs/matriz_formulas.md` antes de tocar código.

- Herramientas: `uv run`, `uv add`, Python 3.14, pytest, ruff. Comentarios y mensajes en español.
- Pruebas: `uv run pytest`; estilo: `uv run ruff check .` y `uv run ruff format --check .`.
- Flujo: un paso a la vez (plan, aprobación, implementación, pruebas, aprobación). No añadir funcionalidades fuera de alcance; ante ambigüedad de diseño, preguntar.
- Fuera de git: `config/config.toml`, `data/`, `firmware/**/secrets.h`.
- Fuera de alcance: reconocimiento facial, Streamlit, BLE, quórum, Partes 2 y 3.
