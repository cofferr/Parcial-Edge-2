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
10. **Tprop del gateway y de DroidCam** son la misma IP (el celular del hotspot). Se midieron y se reportan ambos. El connect TCP al gateway no se mide (no expone puerto).
11. **Intentos fallidos conservados en `data/raw`** (no se borró nada): una serie de tprop con `/status` caído al inicio, una con 97 muestras ICMP de la ESP32, 5 corridas aisladas de DroidCam inválidas por un defecto del parser (ya corregido) y un e2e de DroidCam con 311 errores de 320 (ya excluido por el análisis).


---

# Parte 2 y cálculos de la Parte 3 (rama `worktree-Punto2`, 2026-10-28)

Código y pruebas: todo commiteado por módulo (sin push). Decisiones menores: `docs/DECISIONES_AUTONOMAS.md` (filas del 2026-10-28). Lo que debes hacer en el hardware: `docs/CHECKLIST_HARDWARE_P2.md`.

## Datos que solo tú puedes dar (obligatorios)

1. **`distancia_esp32_ap_m`** (distancia física ESP32-CAM → punto de acceso, en metros) en `[energia]` de `config/config.toml`. Sin ella `scripts/t3_energia.py` se niega a correr (a propósito). Ya están en `[energia]` los valores de referencia de E_elec, E_fs y E_mp.
2. **Cita de E_elec, E_fs y E_mp** (Heinzelman, Chandrakasan y Balakrishnan, IEEE Trans. Wireless Commun., 2002): el campo `cita` dice «referencia por verificar». Tú verificas valores y cita.
3. **Cita de `velocidad_nominal_fuente`** de la ESP32 (heredado de la Parte 1, punto 1).

## Pasos con hardware pendientes (esperan tu aviso)

4. **Prueba de quórum**: ejecutada el 2026-10-28 (11:38–11:41), aceptada por el autor tal cual para el informe. Resultado **sin editar**: A cumple (26 de 35 ventanas con alerta), B cumple (3 de 35; el criterio solo exige ≥ 1 alerta), **C NO cumple** (22 de 34 con alerta; se esperaba ninguna). Causa probable: los trapos no oscurecieron la ESP32-CAM ni DroidCam (nunca se marcaron `tapada`; solo lo hizo la cámara del Mac) y el autor tapó y se movió sin orden fijo, así que las fases no se ajustaron al guion. La lógica del quórum fue coherente con los votos (alerta si y solo si ≥ 2 votos True). Evidencia: `docs/T2_3_RESULTADOS.md`, `docs/evidencia/`.
5. **Corrida de capas de 5 min** (`scripts/t2_4_capas.py`): no la lancé.
6. ~~nmap UDP~~: hecho por el autor; resultados definitivos (AS principal 6,0 y 11,0; secundario de aplicación 2,0). Ver DISENO §26.

## A copiar a mano o revisar

7. **`config/config.toml` está fuera de git**: el del worktree (`.claude/worktrees/Punto2/config/config.toml`) tiene las secciones nuevas `[quorum]`, `[detector.esp32|droidcam|local]` (calibradas) y `[energia]`. Cópialas al `config.toml` del repo principal si vas a ejecutar desde allí. `config.example.toml` (versionado) lleva la plantilla sin IPs ni valores calibrados.
8. **Datos**: en el worktree, `data/raw/*`, `data/processed/*` y la grabación de `data/recordings/` son enlaces simbólicos al repo principal (ignorados por git). Las corridas nuevas (auditoría, quórum, capas) se crean en el `data/` **del worktree**.
9. **Contrato de datos** (`docs/CONTRATO_DATOS.md`, que no modifiqué): `eventos.csv` escribe votos y `alerta` como `1`/`0`; las rutas salen de `[rutas] eventos_csv` y `estado_json` (por defecto `data/eventos.csv` y `data/estado.json`); en `estado.json` el núcleo declara `ble` y `servicio_rostros` como `vivo: false` («no reportado por el núcleo»). Quien lea esos archivos (panel) debe saberlo.
10. **Resultado del detector (evaluación offline sobre los 150 s guionizados, por ventana de 1 s)**: local 100 % de aciertos, DroidCam 96,2 %, ESP32 83,1 % (3 falsos positivos de 65 ventanas estáticas y 19 falsos negativos de 65 de actividad); el quórum Q = 2 acierta 98,5 % con 0 falsos positivos. La ESP32 (≈ 5 fps irregulares, ruido de su JPEG en gris) es la fuente más débil. **Ajuste posterior:** con `umbral_voto = 0.6` la ESP32 pasa a 0 FP de 65 (objetivo ≤ 1 %) pero su sensibilidad baja de 70,8 % a 63,1 % (aciertos 81,5 %); el quórum no cambia (98,5 %, 0 FP). Curva completa en `data/processed/t2_2_barrido_esp32.csv` y DISENO §23; el barrido es optimista (mismas ventanas que la evaluación). Detalle en `data/processed/t2_2_evaluacion.csv`.
11. **Calibración**: tuve que descartar los primeros 5 s del segmento de calibración de 60 s (la persona se movía ~4 s al empezar la grabación). Con los 60 s completos, T_pix salía 94–96 y el detector casi no detectaba actividad. Si repites la grabación, quédate quieto desde el segundo 0.
