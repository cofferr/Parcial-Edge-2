# URGENTE: pendientes de la sección 1 (para tratar mañana)

Estado al 2026-10-27, después de las mediciones con hardware. Código y pruebas: todo commiteado (240 pruebas pasando, sin push). Datos en `data/raw`, `data/recordings` y `data/processed`, fuera de git y **sin respaldo** (ver punto 7).

## Requiere tu decisión o dato

1. **Cita de `velocidad_nominal_fuente` de la ESP32** (`config/config.toml`). Hoy dice "Tabla MCS IEEE 802.11n: HT20, MCS7, 1 flujo, guarda corta (cita pendiente)". El L teórico y la brecha de velocidad de la ESP32 usan 72,2 Mbps; falta la referencia final.
2. **Discrepancias de L (Tarea 1.5), resultados reales sin explicar del todo:**
   - ESP32: L teórico 209 ms, L medido 355 ms (+70 %). tproc_dispositivo medio 187 ms; el RTT ICMP de la ESP32 es alto y variable (media 42 ms, p95 63 ms). No se desglosó los 146 ms restantes.
   - DroidCam: L teórico 15 ms, L medido 483 ms (+3045 %). Unos 450 ms pasan entre la petición y el primer byte (arranque del stream tras abrir la conexión); la fórmula L = ttx + tprop + tproc no lo incluye. Decidir cómo presentarlo (limitación del modelo, o un término extra de arranque).
3. **Interpretación de las Tareas 1.2 y 1.3** (el enunciado no está en el repo): se tomó 1.2 = tamaño del fotograma, 1.3 = tiempo de transmisión ttx (con velocidad efectiva y FPS). Revisar contra el enunciado.
4. **Definición de f (Tarea 1.6):** se tomó f = fracción *transmitida* y ahorro A = (1−f)·D. Revisar contra el enunciado. Todas las decisiones autónomas están en `docs/DECISIONES_AUTONOMAS.md`.
5. **Tarea 1.1:** se lanzó el script, pero falta que confirmes que tomaste las capturas de pantalla.

## Limitaciones a declarar en el informe

6. **Sin prueba A/B de estabilidad de la ESP32** (se eliminó por tu decisión). Como evidencia informal: todo el sistema estuvo encendido ≈ 1 h seguida durante todas las mediciones, y en cada corrida con ESP32 el `fw` coincidió al inicio y al fin (`esp32cam-parcial2-v1`), incluida la grabación de la Tarea 1.6 (la última). No hay un chequeo posterior a la grabación porque la ESP32 se desconectó al terminar.
7. **Datos sin respaldo:** `data/raw` (2,7 MB), `data/processed` (224 KB) y `data/recordings` (1 GB, contiene rostros: no subir a git). Hacer copia fuera del repo.
8. **Glass-to-glass no medido** (Paso 9, fuera de alcance): el e2e termina al decodificar en el Mac, no en pantalla.
9. **ESP32 en la grabación de la Tarea 1.6:** solo ≈ 2,5 FPS con las tres fuentes activas (92 fotogramas de calibración, 201 quietos, 191 de actividad). Su T_area calibrado (0,28) es alto por el ruido de su imagen en gris con JPEG q50; filtra menos que las otras fuentes.
10. **Tprop del gateway y de DroidCam** son la misma IP (172.19.160.129, el celular del hotspot). Se midieron y se reportan ambos. El connect TCP al gateway no se mide (no expone puerto).
11. **Intentos fallidos conservados en `data/raw`** (no se borró nada): una serie de tprop con `/status` caído al inicio, una con 97 muestras ICMP de la ESP32, 5 corridas aisladas de DroidCam inválidas por un defecto del parser (ya corregido) y un e2e de DroidCam con 311 errores de 320 (ya excluido por el análisis).

## Rama streamlit-app (2026-10-28): pendientes del autor

12. ~~Rostros conocidos~~ Resuelto: copiados a `rostros_conocidos/` (ignorada por git), una foto por persona nombrada con la identidad.
13. **Factores de reducción del servicio de rostros** (`esp32=1.0`, `droidcam=0.5`, `local=0.25`): valores iniciales sin validar con hardware; procedimiento de calibración en `docs/INTEGRACION.md`.
14. **Definición de Q y regla de alerta:** el simulador usa `Q = n_true/3` y `alerta = n_true ≥ 2`, inventados solo para probar el panel. El panel muestra Q tal cual lo escriba el núcleo.
15. ~~Quién escribe `reconocimientos.csv`~~ Resuelto: lo escribe el núcleo; el servicio de rostros no lo toca (contrato actualizado).
16. **Rutas en la config:** tarea de la unión (ver `docs/INTEGRACION.md`); en esta rama quedan `--data-dir` / `EDGE_DATA_DIR`.
17. **IP de la sesión (ESP32-CAM 172.19.160.181, DroidCam 172.19.160.129):** los módulos de esta rama no las usan; van solo en `config/config.toml` local (ignorado).
18. **Sin hardware:** BLE, rostros y panel se probaron con un cliente BLE simulado, un reconocedor falso (más dlib sobre imagen vacía) y datos simulados. Falta una prueba con la ESP32 real y con una cara real.

Streamlit, dlib y face_recognition instalaron sin problemas en Python 3.14: no hizo falta alternativa ni reconocedor falso por defecto.
