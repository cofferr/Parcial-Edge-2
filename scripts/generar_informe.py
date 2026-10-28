"""Genera informe/informe-parcial.md (borrador del informe) desde data/processed, data/raw y docs/.

    uv run python scripts/generar_informe.py [--salida informe/informe-parcial.md]

Ningún número se escribe a mano: todo valor sale de un CSV/JSON del proyecto (con su ruta) a
través de `tabla()` y `v()`. Los CSV conservan los valores sin redondear; el borrador solo
redondea al presentar (3 decimales; notación científica por debajo de 1e-3).
"""

import argparse
import csv
import json
import re
import sys
import tomllib
from pathlib import Path

from generar_traspaso import NOTA_FASE_C

from edge_parcial.config import RAIZ

PROC = "data/processed/"
SIN_DATO = "—"
PEND = "[PENDIENTE: lo redacta el consultor]"
CITA = "[CITA PENDIENTE]"


# ---------------------------------------------------------------- lectura y formato
def filas(rel: str) -> list[dict]:
    with (RAIZ / PROC / rel).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def fmt(x: str) -> str:
    """Presentación de una celda: el dato original no se toca, solo se redondea al mostrar."""
    if x is None or x == "":
        return SIN_DATO
    if x in ("True", "False"):
        return "sí" if x == "True" else "no"
    try:
        n = float(x)
    except ValueError:
        return x.replace("|", "\\|")
    if n == int(n) and "e" not in x.lower():
        return str(int(n))
    if n != 0 and abs(n) < 1e-3:
        return f"{n:.3e}"
    return f"{n:.3f}"


def cumple(fila: dict, filtro: dict) -> bool:
    return all(fila.get(k) == str(val) for k, val in filtro.items())


def v(rel: str, col: str, **filtro) -> str:
    """Valor presentado de `col` en la única fila de `rel` que cumple el filtro."""
    c = [f for f in filas(rel) if cumple(f, filtro)]
    if len(c) != 1:
        raise ValueError(f"{rel}: el filtro {filtro} da {len(c)} filas")
    return fmt(c[0][col])


def origen(rel: str) -> str:
    return f"_(origen: `{PROC}{rel}`)_"


def tabla(
    rel: str, cols: list[str] | None = None, titulos: dict | None = None, **filtro
) -> str:
    datos = [f for f in filas(rel) if cumple(f, filtro)]
    cols = cols or list(datos[0])
    titulos = titulos or {}
    cab = "| " + " | ".join(titulos.get(c, c) for c in cols) + " |"
    sep = "|" + "---|" * len(cols)
    cuerpo = ["| " + " | ".join(fmt(f[c]) for c in cols) + " |" for f in datos]
    return "\n".join([cab, sep, *cuerpo, "", origen(rel), ""])


def leer_json(rel: str) -> dict:
    return json.loads((RAIZ / rel).read_text(encoding="utf-8"))


def cfg_ejemplo() -> dict:
    return tomllib.loads(
        (RAIZ / "config" / "config.example.toml").read_text(encoding="utf-8")
    )


def bloque_numeros(titulo: str, partes: list[str]) -> str:
    return f"**Números disponibles para {titulo}:**\n\n" + "\n".join(partes) + "\n"


# ---------------------------------------------------------------- secciones
def encabezado() -> str:
    return f"""# Informe del parcial práctico: estación de monitoreo inteligente en el Edge

> Borrador generado por `scripts/generar_informe.py`. No lo edites a mano: regenéralo.
> **Trazabilidad:** cada número lleva entre paréntesis la ruta del CSV o JSON del que sale.
> **Redondeo:** los CSV y los datos crudos (`data/raw/<run_id>/frames.csv`, marcas en ns) conservan
> los valores sin redondear; este documento redondea solo al presentar (3 decimales; notación
> científica por debajo de 1e-3). Los `.tex` de `data/processed/` llevan el mismo redondeo de presentación.
> **Parámetros de diseño** (60 s, 150 s, 1871 puertos, 160×120, 28 800 s, etc.) se citan de `docs/DISENO.md` y de `config/config.example.toml`, con su sección.
> **Marcadores:** `{PEND}` = sección que redacta el consultor (se dejan debajo todos los números);
> `{CITA}` = falta una referencia verificable; no se inventaron referencias.
> **Enunciado:** `EC_Segundo_Parcial_Practico_.pdf` (22 de octubre de 2026).
"""


def formulas() -> str:
    c = cfg_ejemplo()
    en = c["energia"]
    return f"""## Fórmulas aplicadas

Una fila por expresión del formulario de referencia del enunciado: dónde se aplica y de dónde sale cada valor.

| Fórmula | Tarea | Fuente de cada valor |
|---|---|---|
| $t_{{prop}} = d / v$ | 1.4 (contraste físico) | $d$ de `[esp32]`, `[droidcam]`, `[local]` de `config/config.example.toml`; $v$ = `[propagacion] v_m_s` (c). Valor: ESP32 `tprop_fisico_ns` = {v("tablas/t1_4_tprop.csv", "tprop_fisico_ns", fuente="esp32")} ns (`{PROC}tablas/t1_4_tprop.csv`). tprop medido = RTT ICMP/2 (misma tabla). |
| $t_{{tx}} = \\text{{bits}} / \\text{{velocidad}}$ | 1.3 y 1.5 | bits = carga JPEG medida (`{PROC}tablas/t1_2_tamano_aislada.csv`); velocidad nominal: ESP32 = `[esp32] velocidad_nominal_bps` (config), DroidCam = tasa Wi-Fi del Mac en la metadata de la corrida. Teórico vs real: `{PROC}tablas/t1_5_brecha_velocidad.csv`. |
| $L = t_{{tx}} + t_{{prop}} + t_{{proc}}$ | 1.5 | $t_{{tx}}$ (1.2/config), $t_{{prop}}$ (1.4), $t_{{proc}}$ = dispositivo (cabeceras `X-*` de la ESP32) + decodificación en el host. Tabla: `{PROC}tablas/t1_5_latencia.csv`. |
| $A = (1 - f) \\times D$ | 1.6 | $f$ de `{PROC}t1_6_f.csv`; $D = \\bar S \\cdot \\text{{FPS}} \\cdot 2\\,592\\,000\\ \\text{{s}}$ (mes de 30 días; `{PROC}t1_6_ahorro.csv`). |
| $AS \\approx N \\times I$ | 2.1 | $I$ = puertos abiertos verificados con nmap/lsof (`{PROC}t2_1_interfaces.csv`); $N$ = dispositivos. Resultado: `{PROC}t2_1_as.csv`. |
| $Q = \\lfloor N/2 \\rfloor + 1$ | 2.3 | $N$ = `[quorum] n` = {c["quorum"]["n"]} (`config/config.example.toml`). Para $N = 3$: $Q = \\lfloor 3/2 \\rfloor + 1 = 2$. |
| $L_{{total}} = L_{{device}} + L_{{edge}} + L_{{fog}} + L_{{cloud}}$ | 2.4 | Marcas `perf_counter_ns` por frontera (`{PROC}t2_4_capas.csv`). Sin capa Cloud: $L_{{cloud}}$ no existe en este pipeline (el enunciado lo prevé). |
| $E_{{Tx}}(k, d)$ (LEACH) | 3.1, 3.2 | $k$ de la Tarea 1.2 (`{PROC}t3_1_energia_fotograma.csv`); $d$ = `[energia] distancia_esp32_ap_m` = {c["energia"]["distancia_esp32_ap_m"]} m; $E_{{elec}}$ = {en["e_elec_j_bit"]:.3e}, $E_{{fs}}$ = {en["e_fs_j_bit_m2"]:.3e}, $E_{{mp}}$ = {en["e_mp_j_bit_m4"]:.3e} (config; cita: {CITA}, la config dice «{en["cita"]}»). |
| $d_0 = \\sqrt{{E_{{fs}}/E_{{mp}}}}$ | 3.1 | $d_0$ = {v("t3_1_energia_fotograma.csv", "d0_m", k_tipo="media")} m (`{PROC}t3_1_energia_fotograma.csv`). |
| $E_{{Rx}}(k) = k\\,E_{{elec}}$ | — | **No aplicada:** las Tareas 3.1 y 3.2 piden solo energía de transmisión. Si se exige aplicarla, falta calcularla (ver cobertura). |
| $L^{{objetivo}}_{{URLLC}} \\le 1$ ms | 3.3 | Referencia del enunciado; `objetivo_ms` en `{PROC}t3_3_latencia_vs_1ms.csv`. |
"""


def t11() -> str:
    return """## Tarea 1.1: conexión simultánea a las tres fuentes

**Qué se pidió:** «Escribe un script en Python que abra al mismo tiempo las tres fuentes de video [...] El script debe mostrar las tres ventanas simultáneamente y permitir cerrarlas de forma controlada.»

**Procedimiento:** `scripts/t1_1_tres_fuentes.py` abre `cv2.VideoCapture(0)` para la cámara local y, para la ESP32-CAM y la cámara IP (DroidCam, MJPEG), las URL de streaming; muestra las tres ventanas y se cierra de forma controlada. Para las mediciones posteriores las fuentes de red se leen con sockets propios, no con `cv2.VideoCapture` (decisión de `docs/DISENO.md` §2).

**n y condiciones:** verificación cualitativa. Hotspot del celular (2,4 GHz), fuentes a menos de 1 m del Mac (`docs/DISENO.md` §1).

**Resultado:** [PENDIENTE: capturas de pantalla de las tres ventanas, que toma el autor (`URGENTE.md`, punto 5 de la Parte 1)].

**Discusión:** el script y la verificación en hardware están hechos; la evidencia gráfica falta.
"""


def t12() -> str:
    cols = [
        "fuente",
        "tipo",
        "n",
        "media",
        "minimo",
        "maximo",
        "desviacion",
        "p50",
        "p95",
    ]
    return f"""## Tarea 1.2: tamaño real de un fotograma

**Qué se pidió:** «captura al menos 100 fotogramas consecutivos y registra el tamaño real en bytes de cada uno [...] Reporta el promedio, el mínimo y el máximo por fuente, y explica por qué varían.»

**Procedimiento:** lectores propios por socket (`docs/DISENO.md` §19). Tamaño = bytes de la carga JPEG tal como llega (con `Content-Length` validado con marcas SOI/EOI; sin él, recorrido de marcadores JPEG). La cámara local no tiene carga de red: se reporta el fotograma bruto (`nbytes`) y el JPEG q=50 de referencia (`docs/DISENO.md` §20.3). Se excluyen el calentamiento, las filas con error y los JPEG inválidos.

**n y condiciones:** 5 corridas por fuente y modo, 300 fotogramas medidos por corrida tras 20 de calentamiento (`docs/DISENO.md` §9); las tablas usan la corrida 1 y el resto se conserva en `{PROC}tablas/t1_2_1_3_corridas_aislada.csv` y `..._concurrente.csv`. Modo aislada (una fuente) y concurrente (las tres a la vez). Tamaños en bytes.

**Resultados, modo aislada:**

{tabla("tablas/t1_2_tamano_aislada.csv", cols)}
**Resultados, modo concurrente:**

{tabla("tablas/t1_2_tamano_concurrente.csv", cols)}
**Discusión (descriptiva):** la ESP32-CAM entrega JPEG de {v("tablas/t1_2_tamano_aislada.csv", "media", fuente="esp32")} B de media (mín. {v("tablas/t1_2_tamano_aislada.csv", "minimo", fuente="esp32")}, máx. {v("tablas/t1_2_tamano_aislada.csv", "maximo", fuente="esp32")}); el JPEG q=50 de la cámara local pesa {v("tablas/t1_2_tamano_aislada.csv", "media", fuente="local", tipo="JPEG q50")} B de media frente a {v("tablas/t1_2_tamano_aislada.csv", "media", fuente="local", tipo="bruto (nbytes)")} B del bruto, que es constante (desviación {v("tablas/t1_2_tamano_aislada.csv", "desviacion", fuente="local", tipo="bruto (nbytes)")}). El tamaño del JPEG varía entre fotogramas de una misma fuente porque la compresión depende del contenido de la escena (detalle y ruido del sensor), no del número de píxeles, que es fijo. DroidCam (aislada) entrega {v("tablas/t1_2_tamano_aislada.csv", "media", fuente="droidcam")} B de media (mín. {v("tablas/t1_2_tamano_aislada.csv", "minimo", fuente="droidcam")}, máx. {v("tablas/t1_2_tamano_aislada.csv", "maximo", fuente="droidcam")}); su tabla procede de la repetición válida (las primeras corridas se descartaron por un defecto del parser, ver «Decisiones y desviaciones»).
"""


def t13() -> str:
    return f"""## Tarea 1.3: medición de $t_{{tx}}$ real

**Qué se pidió:** «Diseña un procedimiento con marcas de tiempo [...] que mida cuánto tarda tu programa en recibir cada fotograma completo, para las tres fuentes. Debes justificar [...] qué momento exacto define el inicio y el fin de esa medición.»

**Procedimiento y justificación del inicio y del fin** (`docs/DISENO.md` §3 y §19.2): reloj `time.perf_counter_ns`, monótono y sin saltos. $t_{{first}}$ = marca del `recv` que contiene el primer byte del delimitador de la parte (en `/capture`, el primer byte de la respuesta HTTP); $t_{{last}}$ = marca del `recv` que contiene el último byte de la carga JPEG; $t_{{tx}}^{{real}} = t_{{last}} - t_{{first}}$. El inicio se fija en el primer byte de la parte (y no en el fin del fotograma anterior) para que un retardo previo al fotograma no se atribuya a la transmisión. Ambas marcas son cotas superiores del arribo al socket: el error máximo es una lectura (`recv`, búfer de 64 KiB) en cada extremo. Si `n_recv = 1`, $t_{{tx}} = 0$ es solo el límite de resolución: esas filas se marcan y se excluyen del promedio (se declara su porcentaje). La velocidad efectiva es bits de la carga / suma de $t_{{tx}}$.

**n y condiciones:** corrida 1, 300 fotogramas medidos tras 20 de calentamiento. $t_{{tx}}$ en ms.

**Resultados, modo aislada:**

{tabla("tablas/t1_3_ttx_aislada.csv")}
**Resultados, modo concurrente:**

{tabla("tablas/t1_3_ttx_concurrente.csv")}
**FPS e interarribos, aislada** (la cámara local no tiene $t_{{tx}}$ de red; su interarribo es entre `t_ready`):

{tabla("tablas/t1_3_fps_aislada.csv")}
**FPS e interarribos, concurrente:**

{tabla("tablas/t1_3_fps_concurrente.csv")}
**Discusión (descriptiva):** en aislada, la ESP32 tiene $t_{{tx}}$ medio de {v("tablas/t1_3_ttx_aislada.csv", "media", fuente="esp32")} ms (p95 {v("tablas/t1_3_ttx_aislada.csv", "p95", fuente="esp32")} ms) con {v("tablas/t1_3_ttx_aislada.csv", "pct_n_recv_1", fuente="esp32")} % de filas con `n_recv = 1` excluidas, y DroidCam {v("tablas/t1_3_ttx_aislada.csv", "media", fuente="droidcam")} ms (p95 {v("tablas/t1_3_ttx_aislada.csv", "p95", fuente="droidcam")} ms). La ESP32 entrega {v("tablas/t1_3_fps_aislada.csv", "fps_medio", fuente="esp32")} FPS medios con {v("tablas/t1_3_fps_aislada.csv", "huecos_mayores_1s", fuente="esp32")} huecos mayores a 1 s; DroidCam y la local rondan {v("tablas/t1_3_fps_aislada.csv", "fps_medio", fuente="droidcam")} y {v("tablas/t1_3_fps_aislada.csv", "fps_medio", fuente="local")} FPS. Los FPS irregulares de la ESP32 impiden suponer 10 FPS: se usa el FPS medio medido (`docs/DISENO.md` §10).
"""


def t14() -> str:
    cols = [
        "fuente",
        "rtt_icmp_ms_n",
        "rtt_icmp_ms_media",
        "rtt_icmp_ms_p95",
        "tprop_icmp_ms_media",
        "tprop_icmp_ms_minimo",
        "tprop_icmp_ms_maximo",
        "tprop_icmp_ms_desviacion",
        "tprop_icmp_ms_p50",
        "tprop_icmp_ms_p95",
        "rtt_tcp_ms_media",
        "tprop_fisico_ns",
    ]
    return f"""## Tarea 1.4: estimación de $t_{{prop}}$

**Qué se pidió:** «obtén una estimación del tiempo de propagación/red hacia cada dispositivo [...] Explica qué relación tiene ese valor con la variable $t_{{prop}}$ del formulario, y qué otros componentes de retraso podría estar incluyendo tu medición además de la propagación pura.»

**Procedimiento** (`docs/DISENO.md` §5): $t_{{prop}} = \\text{{RTT}}_{{ICMP}}/2$ con el enlace en reposo; el RTT por `connect` TCP sirve de contraste; se mide también la línea base a la puerta de enlace. El RTT bajo carga se reporta aparte y nunca entra a la fórmula. El valor físico $d/v$ se calcula con $d$ de la config. La cámara local no tiene enlace: $t_{{prop}} = 0$.

**n y condiciones:** corrida de tprop válida más reciente; tabla en ms excepto la última columna (ns). n por destino en la columna `rtt_icmp_ms_n`.

**Resultados:**

{tabla("tablas/t1_4_tprop.csv", cols)}
**Relación con $t_{{prop}}$ y otros componentes de retraso:** el RTT ICMP/2 estima el tiempo de ida del enlace completo, no la propagación pura. Frente al valor físico $d/v$ ({v("tablas/t1_4_tprop.csv", "tprop_fisico_ns", fuente="esp32")} ns para la distancia de la config) incluye, además: la atención del paquete ICMP/TCP por el dispositivo (la pila de la ESP32-CAM es la que más varía), la contención y el acceso al medio Wi-Fi (CSMA/CA), las colas del punto de acceso (el celular, que es a la vez AP y DroidCam) y el planificador del Mac. La media del RTT ICMP de la ESP32 es {v("tablas/t1_4_tprop.csv", "rtt_icmp_ms_media", fuente="esp32")} ms y su p95 {v("tablas/t1_4_tprop.csv", "rtt_icmp_ms_p95", fuente="esp32")} ms, frente a {v("tablas/t1_4_tprop.csv", "rtt_icmp_ms_media", fuente="droidcam")} ms y {v("tablas/t1_4_tprop.csv", "rtt_icmp_ms_p95", fuente="droidcam")} ms de DroidCam. El gateway y DroidCam son la misma IP (el celular del hotspot).
"""


def t15() -> str:
    lat = [
        "fuente",
        "n",
        "payload_media_B",
        "v_nominal_mbps",
        "ttx_teorico_ms",
        "tprop_ms",
        "tproc_dispositivo_ms",
        "tproc_host_ms",
        "L_teorico_ms",
        "L_medido_ms",
        "discrepancia_ms",
        "discrepancia_pct",
        "L_teorico_p50_ms",
        "L_medido_p50_ms",
        "discrepancia_p50_pct",
        "estado",
    ]
    return f"""## Tarea 1.5: latencia total, teoría vs. medición

**Qué se pidió:** «calcula $L = t_{{tx}} + t_{{prop}} + t_{{proc}}$ para cada fuente [...] y compáralo contra una medición end-to-end directa [...]. Construye una tabla con ambos valores y el porcentaje de diferencia, y argumenta al menos dos causas concretas de esa diferencia.»

**Procedimiento** (`docs/DISENO.md` §7, §8, §21): $L^{{teórico}} = t_{{tx}}^{{teórico}} + t_{{prop}} + t_{{proc}}$ con $t_{{tx}}^{{teórico}} = \\text{{bits medios}} / v_{{nominal}}$, $t_{{prop}}$ = RTT ICMP/2 de la Tarea 1.4 y $t_{{proc}}$ = dispositivo (ESP32 `/capture`: flush + capture + jpeg, de las cabeceras `X-*`) + decodificación en el host (`t_ready − t_decode_ini`); la espera en cola se reporta aparte y no entra. Velocidad nominal de la ESP32 ({
        v("tablas/t1_5_latencia.csv", "v_nominal_mbps", fuente="esp32")
    } Mbps; `[esp32] velocidad_nominal_fuente` de `config/config.example.toml`): «{
        cfg_ejemplo()["esp32"]["velocidad_nominal_fuente"]
    }» DroidCam: tasa Wi-Fi del Mac en la metadata de la corrida (media de inicio y cierre). $L^{{medido}}$ = e2e directo $= t_{{ready}} - t_{{request}}$, de la petición hasta el fotograma decodificado: ESP32 por `/capture` con conexión nueva por muestra (el `connect` queda antes de $t_{{request}}$); DroidCam desde abrir el stream hasta el primer fotograma decodificado; local con `read()` con la cámara abierta (sin modelo de red). Discrepancia $= (L^{{medido}} - L^{{teórico}})/L^{{teórico}}$.

**n y condiciones:** 300 muestras por fuente tras 20 de calentamiento, una fuente a la vez (corrida 1). La corrida e2e de DroidCam con 311 errores de 320 se excluye automáticamente y la repetida válida la reemplaza. Tiempos en ms.

**Resultados (teoría vs. medición):**

{tabla("tablas/t1_5_latencia.csv", lat)}
**Desglose del e2e de la ESP32 (`/capture`).** El tramo $t_{{request}} \\to t_{{first}}$ contiene 0,5 RTT de ida, $t_{{proc}}$ del dispositivo, 0,5 RTT de vuelta del primer byte y un residuo; el `connect` (1 RTT) queda fuera porque $t_{{request}}$ se sella después de conectar. Las medias suman; los p95 no.

{tabla("tablas/t1_5_desglose_esp32.csv")}
**Velocidad efectiva de la ESP32 con las dos coberturas del $t_{{tx}}$** (todas las filas = cota inferior del tiempo; solo `n_recv>1` = sesgada hacia arriba):

{tabla("tablas/t1_5_velocidad_efectiva_esp32.csv")}
**Arranque de DroidCam** ($t_{{arranque}} = t_{{first}} - t_{{request}}$) junto a su entrega en régimen estable (Tarea 1.3):

{tabla("tablas/t1_5_arranque_droidcam.csv")}
**Velocidad nominal frente a efectiva** (solo explica la brecha):

{tabla("tablas/t1_5_brecha_velocidad.csv")}
**Ancho de banda por fuente** (tamaño medio × 8 × FPS medio):

{tabla("tablas/t1_5_ancho_banda.csv")}
**Discusión (descriptiva):** el e2e medido de la ESP32 es {
        v("tablas/t1_5_latencia.csv", "L_medido_ms", fuente="esp32")
    } ms frente a {
        v("tablas/t1_5_latencia.csv", "L_teorico_ms", fuente="esp32")
    } ms teóricos ({
        v("tablas/t1_5_latencia.csv", "discrepancia_pct", fuente="esp32")
    } %); el de la cámara local es {
        v("tablas/t1_5_latencia.csv", "L_medido_ms", fuente="local")
    } ms; el de DroidCam, {
        v("tablas/t1_5_latencia.csv", "L_medido_ms", fuente="droidcam", estado="ok")
    } ms frente a {
        v("tablas/t1_5_latencia.csv", "L_teorico_ms", fuente="droidcam", estado="ok")
    } ms teóricos ({
        v(
            "tablas/t1_5_latencia.csv",
            "discrepancia_pct",
            fuente="droidcam",
            estado="ok",
        )
    } %).

**Análisis crítico «teoría vs. medición» (al menos dos causas concretas):** {PEND}

{
        bloque_numeros(
            "ese análisis",
            [
                f"- ESP32, tramo de arranque: total medido {v('tablas/t1_5_desglose_esp32.csv', 'media_ms', tramo='t_request→t_first', componente='total medido')} ms; red (1 RTT TCP) {v('tablas/t1_5_desglose_esp32.csv', 'media_ms', componente='red (1 RTT TCP: 0,5 ida + 0,5 vuelta)')} ms; tproc dispositivo {v('tablas/t1_5_desglose_esp32.csv', 'media_ms', componente='tproc_dispositivo (flush+capture+jpeg)')} ms; residuo {v('tablas/t1_5_desglose_esp32.csv', 'media_ms', tramo='t_request→t_first', componente='residuo')} ms (`{PROC}tablas/t1_5_desglose_esp32.csv`).",
                f"- ESP32, ttx: medido (todas) {v('tablas/t1_5_desglose_esp32.csv', 'media_ms', componente='ttx medido (todas)')} ms, (solo n_recv>1) {v('tablas/t1_5_desglose_esp32.csv', 'media_ms', componente='ttx medido (solo n_recv>1)')} ms, teórico {v('tablas/t1_5_desglose_esp32.csv', 'media_ms', componente='ttx teórico (todas)')} ms (misma tabla).",
                f"- ESP32, velocidad efectiva {v('tablas/t1_5_velocidad_efectiva_esp32.csv', 'velocidad_efectiva_mbps', cobertura='todas')} Mbps (todas) y {v('tablas/t1_5_velocidad_efectiva_esp32.csv', 'velocidad_efectiva_mbps', cobertura='solo n_recv>1')} Mbps (solo n_recv>1) frente a la nominal de {v('tablas/t1_5_brecha_velocidad.csv', 'v_nominal_mbps', modo='aislada', fuente='esp32')} Mbps (`{PROC}tablas/t1_5_velocidad_efectiva_esp32.csv`, `t1_5_brecha_velocidad.csv`).",
                f"- Decodificación y cola en el host (ESP32): {v('tablas/t1_5_desglose_esp32.csv', 'media_ms', componente='decodificación')} ms y {v('tablas/t1_5_desglose_esp32.csv', 'media_ms', componente='espera en cola')} ms.",
                f"- DroidCam: $t_{{arranque}}$ {v('tablas/t1_5_arranque_droidcam.csv', 'media_ms', componente='t_arranque = t_first − t_request')} ms de un e2e de {v('tablas/t1_5_arranque_droidcam.csv', 'media_ms', componente='e2e medido (t_ready − t_request)')} ms; en régimen estable la entrega ($t_{{ready}} - t_{{first}}$) es {v('tablas/t1_5_arranque_droidcam.csv', 'media_ms', componente='entrega (t_ready − t_first)')} ms (`{PROC}tablas/t1_5_arranque_droidcam.csv`).",
                f"- DroidCam, brecha de velocidad: nominal {v('tablas/t1_5_brecha_velocidad.csv', 'v_nominal_mbps', modo='aislada', fuente='droidcam')} Mbps, efectiva {v('tablas/t1_5_brecha_velocidad.csv', 'v_efectiva_mbps', modo='aislada', fuente='droidcam')} Mbps (`{PROC}tablas/t1_5_brecha_velocidad.csv`).",
                "- El modelo no contempla el arranque del stream de DroidCam ni el establecimiento de conexión/petición HTTP de la ESP32; el e2e medido sí (`docs/DISENO.md` §21).",
            ],
        )
    }"""


def t16() -> str:
    return f"""## Tarea 1.6: ahorro de ancho de banda con filtrado en el borde

**Qué se pidió:** «Implementa un criterio propio de filtrado [...]. Mide $f$ de forma empírica ejecutando tu criterio sobre un video de prueba de al menos 2 minutos por fuente, calcula el ahorro $A$ proyectado a un mes de operación continua, y documenta el umbral que elegiste y por qué.»

**Procedimiento** (`docs/DISENO.md` §12, §13, §14, §22): grabación simultánea de las tres fuentes (`scripts/t1_6_grabar.py`) con 60 s de calibración estática y 150 s guionizados (5 ciclos de 15 s estático + 15 s con actividad). Criterio: gris → reducción a 160×120 → gaussiano 5×5; el fotograma se transmite si la fracción de píxeles con $|\\Delta| > T_{{pix}}$ supera $T_{{area}}$ respecto al **último fotograma transmitido** (el primero siempre se transmite). Elección del umbral, solo con el segmento de calibración: $T_{{pix}}$ = percentil 99,9 del ruido $|f_i - f_{{i-1}}|$ (mín. 1), para que el ruido del sensor no cuente como cambio; $T_{{area}}$ = el menor valor de una rejilla logarítmica (1e-4…0,5) con ≤ 1 % de fotogramas estáticos transmitidos, para quedarse con el filtro más sensible que no transmite el fondo quieto. $f$ = fracción transmitida (por fotogramas y por bytes); ahorro $A = (1-f) \\cdot D$ con $D = \\bar S \\cdot \\text{{FPS}} \\cdot 2\\,592\\,000$ s (mes de 30 días, GB decimales); proyección $f(p) = p \\cdot f_{{act}} + (1-p) \\cdot f_{{est}}$ con $p$ la fracción de tiempo con actividad. Se descarta 1 s tras cada límite de segmento.

**n y condiciones:** segmentos y fotogramas por fuente en las tablas (`n`, `n_tx`, `n_calibracion`).

**Calibración:**

{tabla("t1_6_calibracion.csv")}
**Fracción transmitida $f$ por segmento:**

{tabla("t1_6_f.csv")}
**Datos $D$ y ahorro $A$ por fuente y proyección** (`d_gb` y `a_gb` en GB; `p` = fracción de tiempo con actividad; «real» = la mezcla medida en los ciclos):

{tabla("t1_6_ahorro.csv")}
Figura: `{PROC}t1_6_f_vs_umbral.png` ($f$ frente a $T_{{area}}$, un panel por segmento) y barrido en `{PROC}t1_6_barrido_t_area.csv`.

**Discusión (descriptiva):** en los segmentos estáticos las fracciones transmitidas son {v("t1_6_f.csv", "f_frames", fuente="local", tipo="estatico")} (local), {v("t1_6_f.csv", "f_frames", fuente="esp32", tipo="estatico")} (ESP32) y {v("t1_6_f.csv", "f_frames", fuente="droidcam", tipo="estatico")} (DroidCam); en actividad, {v("t1_6_f.csv", "f_frames", fuente="local", tipo="actividad")}, {v("t1_6_f.csv", "f_frames", fuente="esp32", tipo="actividad")} y {v("t1_6_f.csv", "f_frames", fuente="droidcam", tipo="actividad")}. La ESP32 calibró un $T_{{area}}$ de {v("t1_6_calibracion.csv", "t_area", fuente="esp32")}, mucho mayor que el de las otras fuentes, por el ruido de su imagen en grises con JPEG q=50; solo tiene {v("t1_6_calibracion.csv", "n_calibracion", fuente="esp32")} fotogramas de calibración.
"""


def reto1() -> str:
    cols = [
        "modo",
        "fuente",
        "definicion_L",
        "n",
        "media_ms",
        "p50_ms",
        "p95_ms",
        "maximo_ms",
        "brecha_p95_media_ms",
        "Lmax_ms",
        "cumple",
    ]
    return f"""## Reto experto, sesión 1

**Qué se pidió:** «Propón tú mismo un caso de uso real [...] que exija una latencia máxima $L_{{max}}$ específica. Usando únicamente tus datos medidos, determina cuál de las tres fuentes de video —o combinación de ellas— cumpliría ese requisito, y cuál no.»

**Desarrollo:** {PEND}

**Tabla de apoyo** (generada con `scripts/t1_5_desglose.py --lmax-ms {v("tablas/reto1_latencia.csv", "Lmax_ms", modo="aislada", fuente="local")}`; el criterio es p95 ≤ $L_{{max}}$; el $L_{{max}}$ de la tabla es un parámetro de la herramienta, **no** un caso de uso elegido). Las filas «(régimen)» y las concurrentes usan $t_{{ready}} - t_{{first}}$ porque **no existe una medición e2e concurrente**; solo las filas con definición «e2e» son petición → disponible.

{tabla("tablas/reto1_latencia.csv", cols)}
**Otros números que usaré:** desglose del e2e de la ESP32 y arranque de DroidCam (tablas de la Tarea 1.5); latencia por capas (Tarea 2.4, `{PROC}t2_4_capas.csv`).
"""


def t21() -> str:
    return f"""## Tarea 2.1: auditoría de superficie de ataque

**Qué se pidió:** «identifica *todas* las interfaces de red realmente expuestas [...] Construye la tabla real de $I$ por dispositivo —no la asumas, verifícala— y calcula $AS \\approx N \\times I$ para el conjunto completo. Propón al menos dos medidas de mitigación concretas por cada interfaz expuesta que hayas encontrado.»

**Procedimiento** (`docs/DISENO.md` §26, `scripts/t2_1_auditoria.py`): `nmap` TCP completo (`-p- -Pn -sT --open`, `-sV --version-light`) y UDP aparte (`-sU --top-ports 50`, con privilegios); en el host, `lsof -nP -iTCP -sTCP:LISTEN`. Una interfaz cuenta si el estado es `open` (no `open|filtered`) y escucha en una dirección distinta de loopback. Solo se auditan los objetivos de la config (ESP32-CAM, DroidCam y el host); sin barridos de subred. La ESP32-CAM y DroidCam no admitieron `-p-` (≈ 4 y ≈ 3,5 puertos/s): se acotó el TCP a 1871 puertos (1-1024 ∪ los 1000 más comunes de nmap ∪ puertos conocidos de cámaras), por lo que **$I$ es una cota inferior**. UDP: top 50; el host no se escaneó por UDP. $AS = N \\times I$ con $N$ = dispositivos y $I$ = promedio ($\\sum I / N$), en dos conjuntos: (a) tres fuentes (la cámara local no expone interfaz de red: $I = 0$), (b) las tres más el host. Corrida `data/raw/20261028-102826-auditoria/`.

**n y condiciones:** un escaneo por dispositivo (sin repeticiones).

**Tabla I (interfaces por dispositivo, con propietario):**

{tabla("t2_1_interfaces.csv", ["dispositivo", "puerto", "protocolo", "servicio", "version", "estado", "cuenta_en_I", "propietario", "observaciones"])}
**$AS \\approx N \\times I$** (principal: todas las interfaces expuestas; secundario `I_app`/`AS_app`: solo interfaces de aplicación):

{tabla("t2_1_as.csv")}
**Discusión (descriptiva):** con las tres fuentes, $AS$ = {v("t2_1_as.csv", "AS", conjunto="a_tres_fuentes", fila="total")} ($N$ = {v("t2_1_as.csv", "N", conjunto="a_tres_fuentes", fila="total")}, $I$ medio {v("t2_1_as.csv", "I", conjunto="a_tres_fuentes", fila="total")}); con el host, {v("t2_1_as.csv", "AS", conjunto="b_con_host", fila="total")} ($N$ = {v("t2_1_as.csv", "N", conjunto="b_con_host", fila="total")}, $I$ medio {v("t2_1_as.csv", "I", conjunto="b_con_host", fila="total")}). La interfaz de la ESP32-CAM (80/tcp) responde sin autenticación y en texto plano. El celular es a la vez punto de acceso y fuente de video: sus servicios de AP cuentan como interfaces de la fuente DroidCam pero no son de su aplicación.

**Mitigaciones (al menos dos por interfaz expuesta):** {PEND}

{bloque_numeros("las mitigaciones", [f"- Las {len([f for f in filas('t2_1_interfaces.csv') if f['cuenta_en_I'] == 'True'])} interfaces que cuentan en $I$ y sus observaciones están en la Tabla I de arriba (`{PROC}t2_1_interfaces.csv`).", "- Auditoría: la ESP32 siguió respondiendo `/status` con el mismo `fw` tras el escaneo (`data/raw/20261028-102826-auditoria/auditoria.json`)."])}"""


def t22() -> str:
    bar = next(
        f
        for f in filas("t2_2_barrido_esp32.csv")
        if f["t_area_x"] == "1"
        and f["umbral_voto"] == "0.6"
        and f["min_fotogramas"] == "1"
    )
    return f"""## Tarea 2.2: voto independiente de detección de movimiento

**Qué se pidió:** «Implementa un detector de movimiento simple [...] que corra de forma independiente sobre cada una de las tres fuentes, y que produzca cada segundo un voto booleano (`True`/`False`) por cámara.»

**Procedimiento** (`docs/DISENO.md` §23, `src/edge_parcial/edge/`): mismo preprocesamiento que la Tarea 1.6; referencia temporal = último fotograma con edad ≥ 200 ms; movimiento en el fotograma si la fracción de píxeles con $|\\Delta| > T_{{pix}}$ supera $T_{{area}}$; los cambios globales (iluminación, ≥ 60 % de píxeles) y la cámara tapada (luminancia baja ≥ 1 s) no cuentan como movimiento. Voto por ventana de 1 s: `True` si la fracción de fotogramas con movimiento ≥ `umbral_voto`; sin fotogramas en la ventana, `False` con bandera `sin_datos`. Calibración offline por fuente solo con el segmento estático de 60 s de la grabación de la Tarea 1.6, descartando sus primeros 5 s (movimiento de la persona al inicio). Evaluación por ventana sobre los 150 s guionizados.

**n y condiciones:** ventanas de 1 s; las de actividad y las estáticas por fuente están en la tabla de evaluación.

**Calibración:**

{tabla("t2_2_calibracion.csv")}
**Evaluación por ventana** (con la calibración por criterio, `umbral_voto` 0,3–0,35):

{tabla("t2_2_evaluacion.csv")}
**Ajuste de compromiso de la ESP32-CAM** (`t2_2_barrido_esp32.csv`, fila adoptada: `t_area_x` = {fmt(bar["t_area_x"])}, `umbral_voto` = {fmt(bar["umbral_voto"])}, `min_fotogramas` = {fmt(bar["min_fotogramas"])}): tasa de VP {fmt(bar["tasa_VP"])}, FP {fmt(bar["FP"])}, aciertos {fmt(bar["aciertos"])}, acierto del quórum {fmt(bar["quorum_aciertos"])} con {fmt(bar["quorum_FP"])} FP. El barrido usa las mismas ventanas que la evaluación, de modo que es optimista (`docs/DISENO.md` §23). {origen("t2_2_barrido_esp32.csv")}

**Discusión (descriptiva):** con la calibración por criterio, la ESP32 tiene {v("t2_2_evaluacion.csv", "FP", fuente="esp32")} falsos positivos de {v("t2_2_evaluacion.csv", "ventanas_estaticas", fuente="esp32")} ventanas estáticas y tasa de VP {v("t2_2_evaluacion.csv", "tasa_VP", fuente="esp32")}; DroidCam, {v("t2_2_evaluacion.csv", "tasa_VP", fuente="droidcam")}; la local, {v("t2_2_evaluacion.csv", "tasa_VP", fuente="local")}. La ESP32 es la fuente más débil (≈ 2 fotogramas evaluados por ventana, ruido de su JPEG en grises).
"""


def t23() -> str:
    q = cfg_ejemplo()["quorum"]["n"]
    return f"""## Tarea 2.3: lógica de quórum

**Qué se pidió:** «Con $N = 3$ fuentes votando, deriva tú mismo el valor de $Q$ usando la fórmula del formulario [...] e impleméntalo: solo se dispara una “alerta” si al menos $Q$ de las tres fuentes coinciden en `True` dentro de la misma ventana de un segundo. Después, pruébalo: tapa físicamente una cámara [...]; luego tapa dos y verifica de nuevo. Documenta ambos resultados con capturas o registros de log.»

**Derivación:** $Q = \\lfloor N/2 \\rfloor + 1$ con $N$ = {q} (`[quorum] n`, `config/config.example.toml`): $Q = \\lfloor {q}/2 \\rfloor + 1 = 2$. Con $Q = 2$ la alerta tolera una fuente caída o tapada, pero no dos (`docs/DISENO.md` §24).

**Procedimiento:** `src/edge_parcial/nucleo/` y `fog/`; rejilla única de ventanas de 1 s para las tres fuentes; cada fuente emite su voto al cerrar la ventana más una gracia; una fuente caída, tapada o sin datos cuenta `False`. Prueba física con `scripts/t2_3_prueba_quorum.py`, corrida `data/raw/20261028-113902-quorum/` (registro de consola: `docs/evidencia/t2_3_consola_20261028-113902-quorum.log`; `docs/T2_3_RESULTADOS.md`). Fases: A todas libres con movimiento (debe haber alerta); B una cámara tapada y las otras con movimiento (debe haber alerta); C dos tapadas y la tercera con movimiento (no debe haber alerta). Se descartan 4 s al inicio de cada fase y las ventanas que no caen enteras en ella.

**Resumen por fase de la prueba de quórum** (votos `True` por fuente de las ventanas de cada fase; `alertas` = ventanas con ≥ $Q$ votos):

{tabla("t2_3_resumen.csv")}
{NOTA_FASE_C}

**Discusión (descriptiva):** las fases A y B cumplen lo esperado y la C no ({v("t2_3_resumen.csv", "alertas", fase="C")} alertas en {v("t2_3_resumen.csv", "ventanas", fase="C")} ventanas, cuando se esperaba ninguna). La lógica del quórum fue coherente con los votos registrados (alerta si y solo si ≥ 2 votos `True`); el resultado de la fase C se presenta sin editar.
"""


def t24() -> str:
    res = leer_json(PROC + "t2_4_resumen.json")
    return f"""## Tarea 2.4: latencia empírica por capas

**Qué se pidió:** «Define en tu propio pipeline qué parte del código corresponde a cada capa [...] Inserta marcas de tiempo en cada frontera de capa, mide $L_{{device}}$, $L_{{edge}}$ y $L_{{fog}}$ para cada una de las tres fuentes, y calcula $L_{{total}}$ (sin capa Cloud [...]). Compara los tres resultados y explica la fuente principal de la diferencia.»

**Procedimiento** (`docs/DISENO.md` §25, `scripts/t2_4_capas.py`): las capas son módulos lógicos de un mismo proceso en el Mac, sin red simulada entre ellas. $L_{{device}} = t_{{ready}} - t_{{first}}$ (adquisición + decodificación; en la local, $t_{{request}}$ en lugar de $t_{{first}}$); $L_{{edge}} = t_{{edge\\_fin}} - t_{{ready}}$ (cola + cómputo del detector); $L_{{fog}} = t_{{decision}} - t_{{voto}}$. $L_{{total}} = L_{{device}} + L_{{edge}} + L_{{fog}}$. $L_{{ventana}} = t_{{voto}} - t_{{edge\\_fin}}$ es un término de diseño (espera al cierre de la ventana de 1 s más la gracia) y no entra en $L_{{total}}$; el e2e evento→alerta $= L_{{total}} + L_{{ventana}}$.

**n y condiciones:** corrida `data/raw/20261028-114434-capas/` con `--duracion-s 180` (desviación respecto a los 300 s del plan, ver «Decisiones y desviaciones»): {res["fotogramas"]} fotogramas ({res["fotogramas_validos"]} válidos, {res["fotogramas_tardios"]} tardíos) y {res["ventanas"]} ventanas (`{PROC}t2_4_resumen.json`). Tiempos en ms.

**Resultados por fuente y métrica:**

{tabla("t2_4_capas.csv")}
**Capa que más contribuye a la diferencia entre fuentes** (mayor − menor media por fuente): la capa `{res["capa_que_mas_contribuye"]}` (`{PROC}t2_4_resumen.json`).

{tabla("t2_4_diferencia.csv")}
**e2e evento → alerta por fuente:**

{tabla("t2_4_evento_alerta.csv")}
**Discusión (descriptiva):** $L_{{total}}$ medio de la ESP32 es {v("t2_4_capas.csv", "media", fuente="esp32", metrica="ltotal_ms")} ms (p95 {v("t2_4_capas.csv", "p95", fuente="esp32", metrica="ltotal_ms")} ms), el de DroidCam {v("t2_4_capas.csv", "media", fuente="droidcam", metrica="ltotal_ms")} ms y el de la local {v("t2_4_capas.csv", "media", fuente="local", metrica="ltotal_ms")} ms. La capa device concentra la diferencia ({v("t2_4_diferencia.csv", "pct_de_la_diferencia", capa="device")} % de ella); edge y fog aportan fracciones de ms.
"""


def t25() -> str:
    return f"""## Tarea 2.5: matriz de plataformas

**Qué se pidió:** «Completa una tabla comparando la cámara local, el ESP32-CAM, la cámara IP y el PC anfitrión, con al menos estas columnas: capa de la arquitectura [...], protocolo de comunicación, capacidad de cómputo aproximada, si puede o no correr inferencia de un modelo de IA localmente (justifica el sí o el no), y consumo energético aproximado citando la fuente de cada dato (hoja técnica del fabricante u otra fuente verificable).»

**Matriz:** {PEND}

{
        bloque_numeros(
            "la matriz (solo lo medido en este proyecto; las hojas técnicas son "
            + CITA
            + ")",
            [
                f"- Capa y flujo medido: ESP32 y DroidCam entregan JPEG por HTTP/MJPEG ({v('tablas/t1_2_tamano_aislada.csv', 'media', fuente='esp32')} B de media para la ESP32; `{PROC}tablas/t1_2_tamano_aislada.csv`).",
                f"- FPS medios aislada: ESP32 {v('tablas/t1_3_fps_aislada.csv', 'fps_medio', fuente='esp32')}, DroidCam {v('tablas/t1_3_fps_aislada.csv', 'fps_medio', fuente='droidcam')}, local {v('tablas/t1_3_fps_aislada.csv', 'fps_medio', fuente='local')} (`{PROC}tablas/t1_3_fps_aislada.csv`).",
                f"- Cómputo del detector en el edge (Mac): `edge_computo_ms` medio ESP32 {v('t2_4_capas.csv', 'media', fuente='esp32', metrica='edge_computo_ms')} ms, DroidCam {v('t2_4_capas.csv', 'media', fuente='droidcam', metrica='edge_computo_ms')} ms, local {v('t2_4_capas.csv', 'media', fuente='local', metrica='edge_computo_ms')} ms (`{PROC}t2_4_capas.csv`).",
                f"- tproc del dispositivo ESP32 (cabeceras `X-*`): {v('t2_4_capas.csv', 'media', fuente='esp32', metrica='tproc_dispositivo_ms')} ms en la corrida de capas; {v('tablas/t1_5_latencia.csv', 'tproc_dispositivo_ms', fuente='esp32')} ms en el e2e de `/capture` (`{PROC}t2_4_capas.csv`, `{PROC}tablas/t1_5_latencia.csv`).",
                f"- Energía por fotograma transmitido (ESP32, modelo LEACH): {v('t3_1_energia_fotograma.csv', 'E_Tx_J', k_tipo='media')} J (`{PROC}t3_1_energia_fotograma.csv`).",
                f"- Superficie de ataque por dispositivo: `{PROC}t2_1_as.csv`.",
                "- Cómputo del Mac (PC anfitrión): carga de CPU registrada en la metadata de cada corrida (`data/raw/<run_id>/metadata.json`, campo `cpu`).",
                f"- Faltan, para la matriz: hojas técnicas del fabricante (cómputo, consumo, inferencia de IA) {CITA}.",
            ],
        )
    }"""


def reto2() -> str:
    return f"""## Reto experto, sesión 2

**Qué se pidió:** «Diseña (en un diagrama, no en código) una arquitectura completa Device→Edge→Fog→Cloud para un caso de uso real que elijas libremente, usando las tres cámaras de esta práctica. Para cada capa [...] debes justificar la decisión con al menos una fórmula de las vistas hasta ahora —no basta con dibujar las cajas, cada frontera entre capas debe estar sustentada en un cálculo o en un criterio cuantitativo explícito.»

**Diseño y diagrama:** {PEND}

{
        bloque_numeros(
            "sustentar cada frontera",
            [
                f"- Frontera Device→Edge: $L_{{device}}$ medio por fuente = ESP32 {v('t2_4_capas.csv', 'media', fuente='esp32', metrica='device_ms')} ms, DroidCam {v('t2_4_capas.csv', 'media', fuente='droidcam', metrica='device_ms')} ms, local {v('t2_4_capas.csv', 'media', fuente='local', metrica='device_ms')} ms (`{PROC}t2_4_capas.csv`); e2e de la Tarea 1.5 (`{PROC}tablas/t1_5_latencia.csv`).",
                f"- Frontera Edge→Fog: $L_{{edge}}$ medio ESP32 {v('t2_4_capas.csv', 'media', fuente='esp32', metrica='edge_ms')} ms, DroidCam {v('t2_4_capas.csv', 'media', fuente='droidcam', metrica='edge_ms')} ms, local {v('t2_4_capas.csv', 'media', fuente='local', metrica='edge_ms')} ms; $Q = 2$ con $N = 3$ (Tarea 2.3; fases en `{PROC}t2_3_resumen.csv`).",
                f"- Frontera Fog→Cloud: $L_{{fog}}$ medio ESP32 {v('t2_4_capas.csv', 'media', fuente='esp32', metrica='fog_ms')} ms, DroidCam {v('t2_4_capas.csv', 'media', fuente='droidcam', metrica='fog_ms')} ms, local {v('t2_4_capas.csv', 'media', fuente='local', metrica='fog_ms')} ms; no se midió ninguna capa Cloud.",
                f"- Ahorro de ancho de banda del filtrado en el borde: $A$ total proyectado (mezcla real) {v('t1_6_ahorro.csv', 'a_gb', fuente='TOTAL', p='real')} GB/mes de {v('t1_6_ahorro.csv', 'd_gb', fuente='TOTAL', p='real')} GB/mes (`{PROC}t1_6_ahorro.csv`).",
                f"- Energía: ahorro de {v('t3_2_ahorro_8h.csv', 'ahorro_pct', p='real', criterio_f='f_frames')} % en 8 h con $f$ real por fotogramas (`{PROC}t3_2_ahorro_8h.csv`).",
                f"- Superficie de ataque $AS$ = {v('t2_1_as.csv', 'AS', conjunto='a_tres_fuentes', fila='total')} (tres fuentes) y {v('t2_1_as.csv', 'AS', conjunto='b_con_host', fila='total')} (con el host) (`{PROC}t2_1_as.csv`).",
            ],
        )
    }"""


def t31() -> str:
    en = cfg_ejemplo()["energia"]
    return f"""## Tarea 3.1: estimación de energía de transmisión

**Qué se pidió:** «Usando el tamaño de fotograma que mediste en la Tarea 1.2 (en bits, no en bytes) y una distancia realista entre el ESP32-CAM y tu punto de acceso Wi-Fi [...] aplica el modelo de energía de radio del formulario. [...] decidir, con justificación, qué régimen aplica ($d < d_0$ o $d \\ge d_0$) y de dónde tomas los valores de $E_{{elec}}$, $E_{{fs}}$ y $E_{{mp}}$ (deben venir de una fuente citable, no inventados). Reporta la energía estimada por fotograma transmitido.»

**Procedimiento** (`docs/DISENO.md` §27, `scripts/t3_energia.py`): $k$ = tamaño del fotograma de la ESP32-CAM de la Tarea 1.2 en bits (media, mínimo, máximo; `{PROC}tablas/t1_2_tamano_aislada.csv`); $E_{{Tx}}(k, d) = k E_{{elec}} + k E_{{fs}} d^2$ si $d < d_0$ o $k E_{{elec}} + k E_{{mp}} d^4$ si $d \\ge d_0$, con $d_0 = \\sqrt{{E_{{fs}}/E_{{mp}}}}$. Parámetros de `[energia]` en `config/config.example.toml`: $E_{{elec}}$ = {en["e_elec_j_bit"]:.3e} J/bit, $E_{{fs}}$ = {en["e_fs_j_bit_m2"]:.3e} J/bit/m², $E_{{mp}}$ = {en["e_mp_j_bit_m4"]:.3e} J/bit/m⁴. $d$ = {en["distancia_esp32_ap_m"]} m (estimación del autor, «cota superior del montaje»; la config la declara obligatoria y el script se niega a correr sin ella). **Fuente de los parámetros:** {CITA}; la config registra «{en["cita"]}» y el propio campo dice que la cita está por verificar.

**Régimen y razonamiento** (de `{PROC}t3_1_regimen.csv`): {v("t3_1_regimen.csv", "razonamiento")}

**Resultados** (energía por fotograma transmitido, en J; `k_bits` en bits, `d_m` y `d0_m` en m):

{tabla("t3_1_energia_fotograma.csv")}
**Discusión (descriptiva):** la energía media por fotograma es {v("t3_1_energia_fotograma.csv", "E_Tx_J", k_tipo="media")} J, de la cual el término electrónico es {v("t3_1_energia_fotograma.csv", "E_electronica_J", k_tipo="media")} J y el del amplificador {v("t3_1_energia_fotograma.csv", "E_amplificador_J", k_tipo="media")} J. Como $d$ < $d_0$, el amplificador sigue el modelo de espacio libre.
"""


def t32() -> str:
    return f"""## Tarea 3.2: ahorro energético con filtrado

**Qué se pidió:** «Usando la fracción $f$ que mediste en la Tarea 1.6, compara la energía total estimada de transmitir *todos* los fotogramas de una jornada de 8 horas contra transmitir solo la fracción $f$. Expresa el ahorro en las mismas unidades de tu resultado de la Tarea 3.1 y en porcentaje.»

**Procedimiento:** fotogramas en 8 h = FPS medio de la ESP32 (Tarea 1.3) × 28 800 s; energía de «todos» = fotogramas × $E_{{Tx}}$ por fotograma (Tarea 3.1); energía filtrada = $f$ × la anterior, con $f$ de la ESP32 de la Tarea 1.6 por fotogramas y por bytes, proyectada con $p$ ∈ {{1 %, 5 %, 25 %}} y la mezcla real de actividad (`docs/DISENO.md` §27, §14).

**Resultados** (energías en J):

{tabla("t3_2_ahorro_8h.csv")}
Con todas las columnas intermedias (FPS, segundos, fotogramas transmitidos, energía por fotograma): `{PROC}t3_2_completo.csv`.

**Discusión (descriptiva):** con la mezcla real, transmitir todos los fotogramas cuesta {v("t3_2_ahorro_8h.csv", "E_todos_J", p="real", criterio_f="f_frames")} J y solo la fracción $f$ ({v("t3_2_ahorro_8h.csv", "f", p="real", criterio_f="f_frames")} por fotogramas), {v("t3_2_ahorro_8h.csv", "E_filtrado_J", p="real", criterio_f="f_frames")} J: un ahorro de {v("t3_2_ahorro_8h.csv", "ahorro_J", p="real", criterio_f="f_frames")} J ({v("t3_2_ahorro_8h.csv", "ahorro_pct", p="real", criterio_f="f_frames")} %).
"""


def t33() -> str:
    return f"""## Tarea 3.3: confrontación con el objetivo URLLC

**Qué se pidió:** «Toma la latencia total que mediste para la cámara IP en la Sesión 1 y compárala contra el valor de referencia $L^{{objetivo}}_{{URLLC}}$ del formulario. Argumenta, con tus propios números, por qué ninguna red por sí sola —ni siquiera una 5G con URLLC— resolvería el problema si el procesamiento sigue ocurriendo lejos del dato, y qué papel cumple entonces la arquitectura Edge.»

**Procedimiento** (`docs/DISENO.md` §27, `scripts/t3_energia.py`): se compara el $L$ medido de DroidCam (la cámara IP) con 1 ms, en dos casos: e2e en frío ($t_{{ready}} - t_{{request}}$ abriendo el stream) y entrega en régimen estable ($t_{{ready}} - t_{{first}}$); razón y diferencia absoluta, solo cifras. El enunciado aclara que 1 ms es un valor de referencia, no una meta alcanzable en una red Wi-Fi doméstica.

**Resultados** (ms):

{tabla("t3_3_latencia_vs_1ms.csv")}
**Argumento:** {PEND}

{
        bloque_numeros(
            "ese argumento",
            [
                f"- e2e en frío de DroidCam: media {v('t3_3_latencia_vs_1ms.csv', 'L_medido_ms', caso='e2e en frío', estadistico='media')} ms ({v('t3_3_latencia_vs_1ms.csv', 'razon', caso='e2e en frío', estadistico='media')} veces el objetivo); p95 {v('t3_3_latencia_vs_1ms.csv', 'L_medido_ms', caso='e2e en frío', estadistico='p95')} ms (`{PROC}t3_3_latencia_vs_1ms.csv`).",
                f"- Régimen estable: media {v('t3_3_latencia_vs_1ms.csv', 'L_medido_ms', caso='régimen estable', estadistico='media')} ms ({v('t3_3_latencia_vs_1ms.csv', 'razon', caso='régimen estable', estadistico='media')} veces), p95 {v('t3_3_latencia_vs_1ms.csv', 'L_medido_ms', caso='régimen estable', estadistico='p95')} ms.",
                f"- Componentes de la latencia de DroidCam: $t_{{prop}}$ {v('tablas/t1_5_latencia.csv', 'tprop_ms', fuente='droidcam', estado='ok')} ms, $t_{{tx}}$ teórico {v('tablas/t1_5_latencia.csv', 'ttx_teorico_ms', fuente='droidcam', estado='ok')} ms, decodificación {v('tablas/t1_5_latencia.csv', 'tproc_host_ms', fuente='droidcam', estado='ok')} ms (`{PROC}tablas/t1_5_latencia.csv`); arranque {v('tablas/t1_5_arranque_droidcam.csv', 'media_ms', componente='t_arranque = t_first − t_request')} ms (`{PROC}tablas/t1_5_arranque_droidcam.csv`).",
                f"- Procesamiento en el edge: $L_{{edge}}$ por fuente en `{PROC}t2_4_capas.csv` (DroidCam {v('t2_4_capas.csv', 'media', fuente='droidcam', metrica='edge_ms')} ms de media).",
                f"- e2e evento→alerta por fuente en `{PROC}t2_4_evento_alerta.csv` (DroidCam {v('t2_4_evento_alerta.csv', 'media', grupo='droidcam')} ms de media).",
            ],
        )
    }"""


def limitaciones() -> str:
    meta = leer_json("data/raw/20261027-221644-e2e-c1-droidcam/metadata.json")
    wi, wf = (
        meta["wifi_mac_inicio"]["tasa_transmision_mbps"],
        meta["wifi_mac_fin"]["tasa_transmision_mbps"],
    )
    return f"""## Limitaciones del experimento

Cada factor con la evidencia que lo respalda (cómo lo sabemos).

| Factor | Evidencia |
|---|---|
| ESP32-CAM de un solo cliente y FPS irregular | `{PROC}tablas/t1_3_fps_aislada.csv`: {v("tablas/t1_3_fps_aislada.csv", "fps_medio", fuente="esp32")} FPS medios, {v("tablas/t1_3_fps_aislada.csv", "huecos_mayores_1s", fuente="esp32")} huecos > 1 s, interarribo p95 {v("tablas/t1_3_fps_aislada.csv", "interarribo_ms_p95", fuente="esp32")} ms; `docs/DISENO.md` §10, §17. |
| RTT de la ESP32 alto y variable | `{PROC}tablas/t1_4_tprop.csv`: RTT ICMP medio {v("tablas/t1_4_tprop.csv", "rtt_icmp_ms_media", fuente="esp32")} ms, p95 {v("tablas/t1_4_tprop.csv", "rtt_icmp_ms_p95", fuente="esp32")} ms, desviación de $t_{{prop}}$ {v("tablas/t1_4_tprop.csv", "tprop_icmp_ms_desviacion", fuente="esp32")} ms. |
| Resolución del $t_{{tx}}$ (`n_recv = 1`) | {v("tablas/t1_3_ttx_aislada.csv", "pct_n_recv_1", fuente="esp32")} % de las filas de la ESP32 en aislada quedan en $t_{{tx}} = 0$ por resolución y se excluyen (`{PROC}tablas/t1_3_ttx_aislada.csv`); error máximo de una lectura (`recv`) en cada extremo (`docs/DISENO.md` §19.3). |
| Velocidad nominal frente a efectiva | `{PROC}tablas/t1_5_brecha_velocidad.csv` (razón efectiva/nominal de la ESP32 en aislada: {v("tablas/t1_5_brecha_velocidad.csv", "razon_efectiva_nominal", modo="aislada", fuente="esp32")}); la nominal de la ESP32 es una cifra de la tabla MCS de 802.11n, no de la hoja de datos. |
| Tasa Wi-Fi del Mac cambiante | En la corrida e2e de DroidCam la tasa de transmisión del Mac fue {fmt(str(wi))} Mbps al inicio y {fmt(str(wf))} Mbps al cierre (`data/raw/20261027-221644-e2e-c1-droidcam/metadata.json`); la nominal de DroidCam es esa instantánea (`docs/DISENO.md` §6). |
| Hotspot compartido y gateway = DroidCam | El gateway y DroidCam son la misma IP (el celular, que es AP y fuente): RTT ICMP medio {v("tablas/t1_4_tprop.csv", "rtt_icmp_ms_media", fuente="gateway")} ms (gateway) y {v("tablas/t1_4_tprop.csv", "rtt_icmp_ms_media", fuente="droidcam")} ms (DroidCam) (`{PROC}tablas/t1_4_tprop.csv`; `URGENTE.md`). |
| Antigüedad del cuadro y glass-to-glass no medidas | El e2e termina al decodificar en el Mac, no en pantalla; en `/stream`, DroidCam y local no se mide la antigüedad del cuadro (`docs/DISENO.md` §17, §21). |
| Un modo concurrente sin e2e | No existe una medición e2e concurrente; el Reto 1 usa la entrega en régimen para esas filas (`{PROC}tablas/reto1_latencia.csv`). |
| Corridas excluidas | e2e de DroidCam con 311 de 320 fotogramas con error (`{PROC}tablas/t1_5_latencia_completa.csv`, estado EXCLUIDA) y 5 corridas aisladas de DroidCam inválidas por un defecto del parser (`docs/DECISIONES_AUTONOMAS.md`); los datos siguen en `data/raw/`. |
| Sin prueba A/B de estabilidad de la ESP32 | Evidencia informal: el `fw` coincidió al inicio y al cierre en cada corrida (`URGENTE.md`, limitación 6 de la Parte 1). |
| ESP32 en la grabación de la Tarea 1.6 | Solo {v("t1_6_calibracion.csv", "n_calibracion", fuente="esp32")} fotogramas de calibración y $T_{{area}}$ = {v("t1_6_calibracion.csv", "t_area", fuente="esp32")} (`{PROC}t1_6_calibracion.csv`). |
| Detector débil en la ESP32 | Tasa de VP {v("t2_2_evaluacion.csv", "tasa_VP", fuente="esp32")} y FP {v("t2_2_evaluacion.csv", "FP", fuente="esp32")} con la calibración por criterio (`{PROC}t2_2_evaluacion.csv`); el barrido de compromiso es optimista (mismas ventanas). Calibración con 5 s iniciales descartados (`docs/DISENO.md` §23). |
| Quórum, fase C no cumple | `{PROC}t2_3_resumen.csv`: {v("t2_3_resumen.csv", "alertas", fase="C")} alertas en {v("t2_3_resumen.csv", "ventanas", fase="C")} ventanas; `esp32` y `droidcam` nunca llevan la bandera `tapada` (`data/raw/20261028-113902-quorum/eventos.csv`); `docs/T2_3_RESULTADOS.md`. |
| Auditoría: $I$ es una cota inferior | TCP acotado a 1871 puertos en ESP32-CAM y DroidCam, UDP top 50, UDP del host no escaneado (`docs/DISENO.md` §26; `data/raw/20261028-102826-auditoria/nmap_*_tcp_abortado.*`). |
| Capas en un solo proceso, sin Cloud ni red simulada, 180 s | `{PROC}t2_4_resumen.json` ({leer_json(PROC + "t2_4_resumen.json")["ventanas"]} ventanas); `docs/DISENO.md` §25; `docs/DECISIONES_AUTONOMAS.md`. |
| Parámetros de energía sin cita verificada; distancia estimada | `[energia]` de `config/config.example.toml`: cita «por verificar»; $d$ es una estimación del autor ({CITA}). |
"""


def decisiones() -> str:
    tabla_dec = [
        l
        for l in (RAIZ / "docs" / "DECISIONES_AUTONOMAS.md")
        .read_text(encoding="utf-8")
        .splitlines()
        if l.startswith("|")
    ]
    return f"""## Decisiones y desviaciones

Registro completo de `docs/DECISIONES_AUTONOMAS.md` (cada fila: fecha, paso, decisión, alternativa descartada, motivo):

{chr(10).join(tabla_dec)}

**Desviaciones respecto al plan o al enunciado:**

- Corrida de capas de 180 s en lugar de 300 s (petición del autor; `docs/DECISIONES_AUTONOMAS.md`, fila P2-4).
- Prueba de quórum aceptada con la fase C marcada «no cumple», cifras sin editar (`docs/T2_3_RESULTADOS.md`, fila P2-3).
- Sin capa Cloud (el enunciado prevé que la tarea no llega hasta ahí).
- $t_{{request}}$ de `/capture` sellado tras conectar: el connect queda fuera del e2e de la ESP32 (`docs/DISENO.md` §19.2).
- Interpretación de las Tareas 1.2/1.3/1.6 (tamaño, $t_{{tx}}$, $f$ = fracción transmitida): ver `URGENTE.md`.
"""


def cobertura() -> str:
    R = [
        (
            "Tarea 1.1: script con tres fuentes y ventanas",
            "Tarea 1.1",
            "Hecho; capturas de pantalla pendientes del autor",
        ),
        (
            "Tarea 1.2: ≥ 100 fotogramas, media/mín/máx y por qué varían",
            "Tarea 1.2",
            "Hecho",
        ),
        (
            "Tarea 1.3: procedimiento con marcas y justificación del inicio/fin",
            "Tarea 1.3",
            "Hecho",
        ),
        ("Tarea 1.4: $t_{prop}$, relación y otros componentes", "Tarea 1.4", "Hecho"),
        (
            "Tarea 1.5: tabla L teórico vs. e2e, % y ≥ 2 causas",
            "Tarea 1.5",
            f"Tabla hecha; causas: {PEND}",
        ),
        (
            "Tarea 1.6: criterio, ≥ 2 min por fuente, $A$ mensual, umbral justificado",
            "Tarea 1.6",
            "Hecho",
        ),
        (
            "Reto experto 1",
            "Reto experto, sesión 1",
            f"Tabla de apoyo; desarrollo: {PEND}",
        ),
        (
            "Tarea 2.1: tabla de $I$, $AS$, ≥ 2 mitigaciones por interfaz",
            "Tarea 2.1",
            f"Tabla y $AS$ hechos; mitigaciones: {PEND}",
        ),
        ("Tarea 2.2: voto por cámara por segundo", "Tarea 2.2", "Hecho"),
        (
            "Tarea 2.3: derivar $Q$, implementar, tapar 1 y 2 cámaras, logs",
            "Tarea 2.3",
            "Hecho; fase C no cumple (sin editar)",
        ),
        (
            "Tarea 2.4: $L_{device}$, $L_{edge}$, $L_{fog}$, $L_{total}$ y fuente de la diferencia",
            "Tarea 2.4",
            "Hecho (180 s)",
        ),
        (
            "Tarea 2.5: matriz de plataformas con fuentes",
            "Tarea 2.5",
            f"{PEND}; hojas técnicas {CITA}",
        ),
        (
            "Reto experto 2: diagrama Device→Edge→Fog→Cloud con cálculos",
            "Reto experto, sesión 2",
            f"Números listos; diseño: {PEND}",
        ),
        (
            "Tarea 3.1: $E_{Tx}$ por fotograma, régimen y fuente de parámetros",
            "Tarea 3.1",
            f"Hecho; cita de $E_{{elec}}, E_{{fs}}, E_{{mp}}$: {CITA}",
        ),
        ("Tarea 3.2: ahorro 8 h en J y %", "Tarea 3.2", "Hecho"),
        (
            "Tarea 3.3: confrontación con URLLC y papel del Edge",
            "Tarea 3.3",
            f"Cifras hechas; argumento: {PEND}",
        ),
        (
            "Entregable 1: tablas de datos crudos sin redondear",
            "Tablas de cada tarea; `data/raw/`",
            "Los CSV crudos están sin redondear; este borrador redondea solo al presentar",
        ),
        (
            "Entregable 2: cada fórmula aplicada con la fuente de cada valor",
            "Fórmulas aplicadas",
            "Hecho salvo $E_{Rx}$ (no aplicada)",
        ),
        (
            "Entregable 3: los dos retos desarrollados por completo",
            "Retos expertos",
            PEND,
        ),
        (
            "Entregable 4: limitaciones del experimento y cómo se sabe",
            "Limitaciones del experimento",
            "Hecho",
        ),
    ]
    cuerpo = "\n".join(f"| {a} | {b} | {c} |" for a, b, c in R)
    return f"""## Cobertura del enunciado

| Requisito | Sección | Estado |
|---|---|---|
{cuerpo}
"""


def overleaf() -> str:
    tex = sorted(
        p.relative_to(RAIZ).as_posix()
        for p in (RAIZ / "data" / "processed").glob("*.tex")
    )
    tex += sorted(
        p.relative_to(RAIZ).as_posix()
        for p in (RAIZ / "data" / "processed" / "tablas").glob("*.tex")
    )
    png = sorted(
        p.relative_to(RAIZ).as_posix()
        for p in (RAIZ / "data" / "processed").glob("*.png")
    )
    lista = "\n".join(f"- `{p}`" for p in [*tex, *png])
    return f"""## Archivos para subir a Overleaf

**Esqueleto:** `informe/main.tex` y `informe/secciones/01_parte1.tex` … `05_limitaciones.tex`. Compila con XeLaTeX (usa `fontspec`; en Overleaf, compilador «XeLaTeX»). Las rutas de las tablas están en los macros `\\tablas` (carpeta `tablas/`) y `\\procesado`, definidos al inicio de `main.tex`; si subes los archivos a otra estructura, ajusta esos dos macros y `\\graphicspath`.

**Tablas (`.tex`, con redondeo de presentación) y figuras:**

{lista}

Los CSV sin redondear (`data/processed/**/*.csv`) y los datos crudos (`data/raw/`) no hacen falta en Overleaf; `data/recordings/` contiene rostros y no debe subirse.
"""


def generar() -> str:
    partes = [
        encabezado(),
        formulas(),
        "# Parte 1: caracterización empírica de latencia y ancho de banda\n",
        t11(),
        t12(),
        t13(),
        t14(),
        t15(),
        t16(),
        reto1(),
        "# Parte 2: seguridad, gestión distribuida, arquitectura por capas y plataformas\n",
        t21(),
        t22(),
        t23(),
        t24(),
        t25(),
        reto2(),
        "# Parte 3: Edge-of-Things, redes de sensores y 5G\n",
        t31(),
        t32(),
        t33(),
        "# Cierre\n",
        limitaciones(),
        decisiones(),
        cobertura(),
        overleaf(),
    ]
    return "\n".join(partes)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--salida", type=Path, default=RAIZ / "informe" / "informe-parcial.md"
    )
    args = ap.parse_args(argv)
    texto = generar()
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(texto, encoding="utf-8")
    print(
        f"Escrito {args.salida} ({len(texto.splitlines())} líneas, {len(re.findall(r'PENDIENTE', texto))} marcadores)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
