# edge-parcial

Parcial práctico de Edge Computing: caracterización empírica de latencia y ancho de banda de tres
fuentes de video (cámara local, ESP32-CAM, DroidCam), más una demo de detección por quórum y una
estimación de energía.

## Qué hace

- **Parte 1 (latencia y ancho de banda):** mide tprop, ttx y tproc de cada fuente, calcula la
  latencia total L (teórica y medida) y el ancho de banda ahorrado al transmitir solo los fotogramas
  con cambio (filtro por diferencia).
- **Parte 2 (superficie de ataque, detección y capas):** auditoría de interfaces expuestas (AS ≈ N × I),
  detector de movimiento por fuente (edge), quórum Q(N) = ⌊N/2⌋ + 1 entre fuentes (fog) y latencia
  por capas.
- **Parte 3 (energía):** modelo LEACH de radio de primer orden para la ESP32-CAM y comparación de la
  latencia con el objetivo URLLC de 1 ms.
- **Demo:** panel en Streamlit con vista en vivo, historial, alertas y reconocimiento de rostros;
  telemetría de la estación ESP32 por BLE.

## Estructura

| Ruta | Contenido |
|---|---|
| `src/edge_parcial/acquisition/` | Lectores de las fuentes (red cruda MJPEG, cámara local), grabador y verificación |
| `src/edge_parcial/analysis/` | Cálculos: tprop, ttx, latencia, ahorro de ancho de banda, auditoría, energía, tablas y figuras |
| `src/edge_parcial/edge/`, `fog/`, `capas/` | Detector de movimiento, quórum y latencia por capas |
| `src/edge_parcial/nucleo/`, `panel/`, `visor/`, `rostros/`, `ble/` | Núcleo de ejecución, componentes de la demo y módulo BLE |
| `app/` | Panel Streamlit (`app/main.py` y `app/paginas/`) |
| `scripts/` | Scripts de medición y análisis por tarea (`t1_*`, `t2_*`, `t3_*`), `demo.py` y `generar_informe.py` |
| `firmware/esp32cam/` | Firmware de la ESP32-CAM y plantilla de credenciales |
| `config/` | `config.example.toml` (copiar a `config.toml`) |
| `docs/` | Diseño, matriz de fórmulas, contrato de datos y checklists de hardware |
| `informe/` | Informe en LaTeX (`main.tex`, `secciones/`, `tablas_informe/`) y borrador en Markdown |
| `data/` | `raw/`, `recordings/` y `processed/` (fuera de git) |

## Puesta en marcha

Requiere Python 3.14 y [uv](https://docs.astral.sh/uv/).

```sh
uv sync
cp config/config.example.toml config/config.toml   # ajustar IP de las fuentes y parámetros
```

Para el firmware: `cp firmware/esp32cam/secrets.example.h firmware/esp32cam/secrets.h` y completar
`WIFI_SSID` y `WIFI_PASS`. Ver `firmware/esp32cam/README.md`.

### Uso

```sh
uv run python scripts/demo.py             # demo completa (con hardware BLE)
uv run python scripts/demo.py --simular   # datos simulados, sin BLE
uv run streamlit run app/main.py          # solo el panel (lanza los componentes)
uv run python scripts/generar_informe.py  # regenera informe/informe-parcial.md
```

Los scripts de cada tarea se ejecutan con `uv run python scripts/<nombre>.py`; el orden de las
mediciones con hardware está en `docs/CHECKLIST_HARDWARE.md`.

### Pruebas y estilo

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Cómo se calculan los resultados

Los scripts de `scripts/` usan los módulos de `src/edge_parcial/analysis/` y escriben CSV/JSON en
`data/processed/`. `scripts/generar_informe.py` lee esos archivos para armar el borrador del informe.
La correspondencia entre cada fórmula y el archivo que la calcula está en `docs/matriz_formulas.md`.

## Cambios respecto a los sistemas anteriores

### Circuito

Se integró la ESP32-CAM al circuito y ahora se alimenta desde la ESP32, en lugar de tener una
alimentación independiente.

### Firmware de la ESP32-CAM

Se cambió el código del firmware:

- Ahora expone **3 endpoints**: `/stream`, `/capture` y `/status` (ver `firmware/esp32cam/README.md`).
- Las imágenes se entregan **en escala de grises**.
- La **resolución por defecto es mucho menor** que antes: 320x240.

El motivo es que la cámara no tiene compresión JPEG por hardware, así que la compresión la hace el
firmware; reducir la resolución y pasar a grises disminuye el costo de esa compresión y el tamaño de
cada fotograma.

## Documentación

- Diseño y decisiones: `docs/DISENO.md`
- Fórmulas y archivos que las calculan: `docs/matriz_formulas.md`
- Contrato de datos: `docs/CONTRATO_DATOS.md`
- Verificación manual del lector con hardware: `docs/verificacion_lector.md`
- Checklists de medición con hardware: `docs/CHECKLIST_HARDWARE.md` y `docs/CHECKLIST_HARDWARE_P2.md`
- Decisiones tomadas de forma autónoma (para revisar): `docs/DECISIONES_AUTONOMAS.md`
- Pendientes abiertos: `URGENTE.md`
