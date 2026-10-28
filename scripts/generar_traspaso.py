"""Genera informe/DATOS_PARA_REDACCION.md desde data/processed y docs/ (sin redondear).

    uv run python scripts/generar_traspaso.py [--salida informe/DATOS_PARA_REDACCION.md]

Las tablas se copian del CSV de origen tal cual (texto sin redondear) con su ruta. Las
IP de la config se enmascaran. Si falta un CSV se avisa en el documento; nada se inventa.
"""

import argparse
import csv
import json
import re
import sys
import tomllib
from pathlib import Path

from edge_parcial.config import RAIZ

PROCESADO = Path("data/processed")
TABLAS = PROCESADO / "tablas"
CLAVES_IP = ("ip", "gateway_ip", "url_imagen_fija")
LIMITE_FILAS = 120  # las tablas más largas se citan por ruta, no se copian enteras

# Cada tarea: qué se midió, procedimiento, n, condiciones y los CSV de resultados.
TAREAS = [
    {
        "id": "1.1",
        "titulo": "Tres fuentes de video funcionando",
        "medido": "Verificación de que las tres fuentes (cámara local, ESP32-CAM, DroidCam) entregan fotogramas.",
        "procedimiento": "`scripts/t1_1_tres_fuentes.py` abre las tres fuentes a la vez (DISENO §1, §22). Las capturas de pantalla las toma el autor (pendiente de confirmar en URGENTE.md).",
        "n": "no aplica (verificación cualitativa)",
        "condiciones": "Hotspot del celular, 2,4 GHz, fuentes a menos de 1 m del Mac (DISENO §1).",
        "tablas": [],
    },
    {
        "id": "1.2",
        "titulo": "Tamaño del fotograma",
        "medido": "Bytes de la carga JPEG por fuente; en la local también el fotograma bruto (BGR) y el JPEG q=50 de referencia (DISENO §3, §20.3).",
        "procedimiento": "Lectores propios por socket (DISENO §19) y `scripts/t1_2_1_3_medicion.py`; análisis en `analysis/tarea_1_2_1_3.py`. Se excluyen warmup, filas con error y JPEG inválido.",
        "n": "5 corridas de 300 fotogramas por fuente y modo, tras 20 de calentamiento (DISENO §9); las tablas oficiales usan la corrida 1.",
        "condiciones": "Modos aislada (una fuente) y concurrente (las tres a la vez).",
        "tablas": [
            "tablas/t1_2_tamano_aislada.csv",
            "tablas/t1_2_tamano_concurrente.csv",
            "tablas/t1_2_1_3_corridas_aislada.csv",
            "tablas/t1_2_1_3_corridas_concurrente.csv",
        ],
    },
    {
        "id": "1.3",
        "titulo": "Tiempo de transmisión y FPS",
        "medido": "ttx = t_last − t_first, velocidad efectiva, FPS medio e interarribos (DISENO §3, §10, §19.3).",
        "procedimiento": "Mismas corridas que 1.2. Las filas con `n_recv = 1` tienen ttx = 0 por resolución y se marcan y excluyen del ttx (su porcentaje se declara).",
        "n": "Ver la columna `n_ttx` y `pct_n_recv_1` de las tablas (corrida 1, 300 fotogramas medidos).",
        "condiciones": "Aislada y concurrente; velocidad nominal según DISENO §6.",
        "tablas": [
            "tablas/t1_3_ttx_aislada.csv",
            "tablas/t1_3_ttx_concurrente.csv",
            "tablas/t1_3_fps_aislada.csv",
            "tablas/t1_3_fps_concurrente.csv",
        ],
    },
    {
        "id": "1.4",
        "titulo": "Tiempo de propagación",
        "medido": "RTT ICMP en reposo (tprop = RTT/2), RTT por connect TCP, línea base a la puerta de enlace, d/v físico y RTT bajo carga (aparte, fuera de la fórmula) (DISENO §5).",
        "procedimiento": "`scripts/t1_4_tprop.py`; resumen en `analysis/tprop.py`. Se usa la corrida de tprop válida más reciente.",
        "n": "≥ 100 muestras ICMP y TCP por destino (120 en la corrida usada).",
        "condiciones": "Reposo (sin carga); distancia de la config.",
        "tablas": ["tablas/t1_4_tprop.csv"],
    },
    {
        "id": "1.5",
        "titulo": "Latencia L = ttx + tprop + tproc y extremo a extremo",
        "medido": "e2e = t_ready − t_request por fuente, frente a L teórico; desglose del e2e de la ESP32 (`/capture`), arranque de DroidCam, velocidad efectiva y ancho de banda (DISENO §8, §21).",
        "procedimiento": "`scripts/t1_5_e2e.py` (una fuente a la vez) y `scripts/t1_5_analisis.py`; el desglose y el arranque salen de `scripts/t1_5_desglose.py` con datos ya medidos. En `/capture`, `t_request` se sella después de conectar, así que el connect queda fuera de t_request→t_first.",
        "n": "300 muestras por fuente tras 20 de calentamiento (corrida 1).",
        "condiciones": "ESP32 por `/capture` con conexión nueva por muestra; DroidCam desde abrir el stream hasta el primer fotograma; local con `read()`. El ttx de la ESP32 se da con dos coberturas (todas las filas, cota inferior; solo `n_recv>1`, sesgada hacia arriba).",
        "tablas": [
            "tablas/t1_5_latencia.csv",
            "tablas/t1_5_desglose_esp32.csv",
            "tablas/t1_5_velocidad_efectiva_esp32.csv",
            "tablas/t1_5_arranque_droidcam.csv",
            "tablas/t1_5_brecha_velocidad.csv",
            "tablas/t1_5_ancho_banda.csv",
        ],
    },
    {
        "id": "1.6",
        "titulo": "Filtro por diferencia y ancho de banda ahorrado",
        "medido": "Fracción transmitida f (por bytes y por fotogramas), D = S̄·FPS·2 592 000 s, A = (1 − f)·D y proyección f(p) (DISENO §12, §14, §22).",
        "procedimiento": "`scripts/t1_6_grabar.py` (60 s de calibración estática y 5 ciclos de 15 s estático / 15 s con actividad, tres fuentes a la vez) y `scripts/t1_6_analisis.py`. T_pix = percentil 99,9 del ruido; T_area = el menor de la rejilla con ≤ 1 % de estáticos transmitidos.",
        "n": "60 s de calibración y 150 s guionizados por fuente; conteos de fotogramas en las tablas.",
        "condiciones": "Referencia = último fotograma transmitido; se descarta 1 s tras cada límite de segmento.",
        "tablas": ["t1_6_calibracion.csv", "t1_6_f.csv", "t1_6_ahorro.csv"],
    },
    {
        "id": "Reto 1",
        "titulo": "Reto experto 1: L por fuente y modo con Lmax",
        "medido": "L (media, p50, p95, máximo), brecha p95 − media y cumple/no cumple con p95 ≤ Lmax, aislada y concurrente.",
        "procedimiento": "`scripts/t1_5_desglose.py --lmax-ms 500`. Aislada = e2e de la Tarea 1.5. **No existe e2e concurrente medido**: en las filas concurrentes de red se usa la entrega en régimen (t_ready − t_first); por eso se añaden las filas «(régimen)» aisladas, comparables con ellas.",
        "n": "300 por fila.",
        "condiciones": "Lmax = 500 ms (parámetro `--lmax-ms`).",
        "tablas": ["tablas/reto1_latencia.csv"],
    },
    {
        "id": "2.1",
        "titulo": "Auditoría de superficie de ataque (AS ≈ N × I)",
        "medido": "Interfaces expuestas por dispositivo (nmap TCP/UDP, lsof del host) y AS en dos conjuntos: (a) tres fuentes, (b) con el host (DISENO §26).",
        "procedimiento": "`scripts/t2_1_auditoria.py`; datos crudos en `data/raw/20261028-102826-auditoria/`. Escaneo TCP acotado a 1871 puertos en ESP32-CAM y DroidCam; host con `-p-`; UDP top 50 (no en el host).",
        "n": "Un escaneo por dispositivo; ver cobertura en DISENO §26.",
        "condiciones": "Solo `open` cuenta en I; I es una cota inferior.",
        "tablas": ["t2_1_interfaces.csv", "t2_1_as.csv"],
    },
    {
        "id": "2.2",
        "titulo": "Detector de movimiento y voto por ventana",
        "medido": "Calibración offline por fuente, evaluación por ventana de 1 s (VP, FN, FP, VN) y barrido de compromiso de la ESP32-CAM (DISENO §23).",
        "procedimiento": "`scripts/t2_2_calibrar.py` y `scripts/t2_2_barrido_esp32.py` sobre la grabación de la Tarea 1.6, descartando los primeros 5 s de la calibración.",
        "n": "Ventanas de 1 s sobre 150 s guionizados (65 estáticas y 65 de actividad por fuente tras la guarda).",
        "condiciones": "El barrido usa las mismas ventanas que la evaluación (mejora de FP optimista).",
        "tablas": [
            "t2_2_calibracion.csv",
            "t2_2_evaluacion.csv",
            "t2_2_barrido_esp32.csv",
        ],
    },
    {
        "id": "2.3",
        "titulo": "Quórum Q(N) = ⌊N/2⌋ + 1",
        "medido": "Votos por ventana de 1 s de las tres fuentes y alerta cuando n_true ≥ Q (DISENO §24); prueba física en tres fases.",
        "procedimiento": "`scripts/t2_3_prueba_quorum.py`; corrida `20261028-113902-quorum`; consola en `docs/evidencia/t2_3_consola_20261028-113902-quorum.log`; resultados en `docs/T2_3_RESULTADOS.md`.",
        "n": "34–35 ventanas por fase (se descartan 4 s al inicio de cada fase).",
        "condiciones": "N = 3, Q = 2. Fase A: todas libres con movimiento. Fase B: ESP32 tapada y las otras con movimiento. Fase C: ESP32 y DroidCam tapadas y la tercera con movimiento.",
        "tablas": ["t2_3_resumen.csv"],
        "extra": "quorum",
    },
    {
        "id": "2.4",
        "titulo": "Latencia por capas device / edge / fog",
        "medido": "Ldevice, Ledge, Lfog, L_ventana y Ltotal = Ldevice + Ledge + Lfog (sin Cloud); e2e evento→alerta = Ltotal + L_ventana (DISENO §25).",
        "procedimiento": "`scripts/t2_4_capas.py`; corrida `20261028-114434-capas` (`--duracion-s 180` en lugar de 300 s: desviación, ver decisiones).",
        "n": "Ver `t2_4_resumen.json` (fotogramas y ventanas).",
        "condiciones": "Tres fuentes con actividad alternada (ciclos de 15 s); capas como módulos de un mismo proceso, sin red simulada entre ellas.",
        "tablas": [
            "t2_4_resumen.json",
            "t2_4_capas.csv",
            "t2_4_diferencia.csv",
            "t2_4_evento_alerta.csv",
        ],
    },
    {
        "id": "3.1",
        "titulo": "Energía de transmisión por fotograma (modelo de radio de primer orden)",
        "medido": "E_Tx(k, d) para k = tamaño de fotograma de la ESP32-CAM (Tarea 1.2): media, mínimo y máximo (DISENO §27).",
        "procedimiento": "`scripts/t3_energia.py` (`analysis/energia.py`); se niega a correr sin `distancia_esp32_ap_m`.",
        "n": "Tamaños de la Tarea 1.2 (corrida 1).",
        "condiciones": "Régimen decidido comparando d con d0 = √(E_fs / E_mp).",
        "tablas": ["t3_1_energia_fotograma.csv", "t3_1_regimen.csv"],
    },
    {
        "id": "3.2",
        "titulo": "Ahorro de energía en 8 h",
        "medido": "Energía de transmitir todos los fotogramas frente a solo la fracción f (Tarea 1.6, por fotogramas, ESP32) en 28 800 s.",
        "procedimiento": "`scripts/t3_energia.py`.",
        "n": "FPS medido (Tarea 1.3) y f (Tarea 1.6).",
        "condiciones": "8 h = 28 800 s.",
        "tablas": ["t3_2_ahorro_8h.csv", "t3_2_completo.csv"],
    },
    {
        "id": "3.3",
        "titulo": "Latencia frente a URLLC (1 ms)",
        "medido": "L medido de DroidCam (e2e en frío y régimen estable, Reto 1) frente a 1 ms: razón y diferencia absoluta. Solo cifras.",
        "procedimiento": "`scripts/t3_energia.py` sobre los resultados de la Tarea 1.5 y el Reto 1.",
        "n": "300 muestras (Tarea 1.5).",
        "condiciones": "Objetivo de 1 ms.",
        "tablas": ["t3_3_latencia_vs_1ms.csv"],
    },
]

NOTA_FASE_C = (
    "**Fase C (resultado sin editar: NO cumple), en tres partes.**\n\n"
    "(a) *Lo que se hizo:* según la declaración del operador, tapó dos cámaras (esp32 y droidcam) "
    "y se movió frente a la tercera.\n\n"
    "(b) *Lo que muestra el registro:* hubo ventanas con alerta en la fase "
    "(`t2_3_resumen.csv`) y la bandera `tapada` nunca se activó en `esp32` ni en `droidcam` "
    "(`data/raw/20261028-113902-quorum/eventos.csv`); votos por ventana y luminancia, en "
    "`informe/informe-parcial.md`.\n\n"
    "(c) *Lectura honesta:* el sistema no confirma de forma independiente que estuvieran tapadas. "
    "La causa probable es que la tapa no bajó la luminancia por debajo del umbral oscuro, o que el "
    "voto se disparó por otro motivo; el registro no permite distinguirlas y no se califica como "
    "problema de medición sin evidencia. Recomendación: repetir la fase C con tapa opaca."
)


def leer(ruta: Path) -> str:
    return (RAIZ / ruta).read_text(encoding="utf-8")


def tabla_md(ruta: Path) -> str:
    """CSV como tabla Markdown con el texto de las celdas tal cual (sin redondear)."""
    if not (RAIZ / ruta).is_file():
        return f"_Falta `{ruta}`; no se generó._\n"
    filas = list(csv.reader((RAIZ / ruta).open(encoding="utf-8", newline="")))
    if not filas:
        return f"_`{ruta}` está vacío._\n"
    cab, cuerpo = filas[0], filas[1:]
    if len(cuerpo) > LIMITE_FILAS:
        return f"_{len(cuerpo)} filas: se cita por ruta, no se copia aquí._\n"

    def celda(x: str) -> str:
        return x.replace("|", "\\|").replace("\n", " ")

    out = ["| " + " | ".join(map(celda, cab)) + " |", "|" + "---|" * len(cab)]
    out += ["| " + " | ".join(map(celda, f)) + " |" for f in cuerpo]
    return "\n".join(out) + "\n"


def bloque_resultado(rel: str) -> str:
    ruta = (TABLAS if rel.startswith("tablas/") else PROCESADO) / rel.removeprefix(
        "tablas/"
    )
    cabecera = f"**Resultado** — origen: `{ruta}`\n\n"
    if ruta.suffix == ".json":
        if not (RAIZ / ruta).is_file():
            return cabecera + f"_Falta `{ruta}`._\n"
        datos = json.loads(leer(ruta))
        return (
            cabecera
            + "```json\n"
            + json.dumps(datos, ensure_ascii=False, indent=2)
            + "\n```\n"
        )
    return cabecera + tabla_md(ruta)


def seccion_md(texto: str, patron: str) -> str:
    """Texto de la sección `## ...` cuyo título empieza con `patron` (hasta la siguiente `## `)."""
    m = re.search(rf"^## {patron}.*?(?=^## |\Z)", texto, flags=re.DOTALL | re.MULTILINE)
    return (
        m.group(0).rstrip() + "\n"
        if m
        else f"_No se encontró la sección «{patron}»._\n"
    )


def config_enmascarada() -> str:
    """config.example.toml con las IP enmascaradas; los comentarios conservan las citas."""
    salida = []
    for linea in leer(Path("config/config.example.toml")).splitlines():
        m = re.match(r"^(\w+)\s*=", linea)
        if m and m.group(1) in CLAVES_IP:
            linea = f'{m.group(1)} = "<oculta>"'
        salida.append(linea)
    return "\n".join(salida) + "\n"


def parametros_detector() -> str:
    ruta = PROCESADO / "t2_2_parametros.toml"
    if not (RAIZ / ruta).is_file():
        return f"_Falta `{ruta}`._\n"
    tomllib.loads(leer(ruta))  # valida que sea TOML
    return f"Origen: `{ruta}`\n\n```toml\n{leer(ruta).rstrip()}\n```\n"


def limitaciones() -> str:
    urgente = leer(Path("URGENTE.md"))
    m = re.search(
        r"^## Limitaciones a declarar en el informe\n(.*?)(?=^---|^# |\Z)",
        urgente,
        flags=re.DOTALL | re.MULTILINE,
    )
    p1 = (
        m.group(1).strip()
        if m
        else "_No se encontró la sección de limitaciones en URGENTE.md._"
    )
    diseno = leer(Path("docs/DISENO.md"))
    return "\n\n".join(
        [
            "### Parte 1 (`URGENTE.md`, «Limitaciones a declarar en el informe»)\n\n"
            + p1,
            "### Parte 1 (`docs/DISENO.md` §17)\n\n"
            + seccion_md(diseno, "17").split("\n", 1)[1].strip(),
            (
                "### Parte 2 y 3 (evidencia en archivos)\n\n"
                "- **Fase C del quórum no cumple** — evidencia: `docs/T2_3_RESULTADOS.md`, `docs/evidencia/t2_3_consola_20261028-113902-quorum.log`, `data/raw/20261028-113902-quorum/eventos.csv`.\n"
                "- **Auditoría: I es una cota inferior** (TCP acotado a 1871 puertos en ESP32-CAM y DroidCam; UDP top 50; UDP del host no escaneado) — evidencia: DISENO §26, `data/raw/20261028-102826-auditoria/nmap_*_tcp_abortado.*`.\n"
                "- **ESP32-CAM, fuente más débil del detector** (≈ 2 fotogramas evaluados por ventana; sensibilidad 63,1 % con `umbral_voto = 0.6`) y barrido optimista (mismas ventanas que la evaluación) — evidencia: `data/processed/t2_2_evaluacion.csv`, `data/processed/t2_2_barrido_esp32.csv`, DISENO §23.\n"
                "- **Corrida de capas de 180 s en vez de 300 s** — evidencia: `data/raw/20261028-114434-capas/`, `docs/DECISIONES_AUTONOMAS.md` (P2-4).\n"
                "- **Capas sin red simulada entre ellas; sin Cloud** — DISENO §25.\n"
                "- **Calibración con 5 s descartados** por movimiento de la persona al inicio — `docs/DECISIONES_AUTONOMAS.md`, URGENTE.md punto 11 de la Parte 2.\n"
                "- **Reto 1 sin e2e concurrente medido** — se usa la entrega en régimen; ver la sección del Reto 1.\n"
                "- **Cita de E_elec, E_fs y E_mp por verificar** por el autor — `config/config.example.toml` (`[energia]`), DISENO §27."
            ),
        ]
    )


def generar() -> str:
    diseno = leer(Path("docs/DISENO.md"))
    p = [
        "# Datos para la redacción del informe\n",
        (
            "Documento generado por `scripts/generar_traspaso.py` desde `data/processed/` y `docs/`. "
            "No lo edites a mano: regenéralo. Los valores se copian de los CSV **sin redondear**; "
            "los `.tex` de `data/processed/` llevan el redondeo de presentación.\n"
        ),
        "## 1. Definiciones y fórmulas usadas\n",
        "Matriz de fórmulas del parcial (`docs/matriz_formulas.md`):\n",
        leer(Path("docs/matriz_formulas.md")).split("\n", 2)[2].strip() + "\n",
    ]
    p.append("### Definiciones de `docs/DISENO.md`\n")
    for patron in (
        "3\\.",
        "6\\.",
        "7\\.",
        "8\\.",
        "12\\.",
        "14\\.",
        "23\\.",
        "24\\.",
        "25\\.",
        "26\\.",
        "27\\.",
    ):
        sec = seccion_md(diseno, patron)
        p.append(sec.replace("\n## ", "\n#### ").replace("## ", "#### ", 1))
    p.append("## 2. Tareas 1.1 a 3.3\n")
    p.append(
        "Las tareas se nombran según el repositorio (el enunciado no está en él); revisar los títulos contra el enunciado.\n"
    )
    for t in TAREAS:
        rotulo = t["id"] if t["id"].startswith("Reto") else f"Tarea {t['id']}"
        p.append(f"### {rotulo}: {t['titulo']}\n")
        p.append(f"- **Qué se midió:** {t['medido']}")
        p.append(f"- **Procedimiento:** {t['procedimiento']}")
        p.append(f"- **n:** {t['n']}")
        p.append(f"- **Condiciones:** {t['condiciones']}\n")
        if not t["tablas"]:
            p.append("_Sin tabla de resultados._\n")
        for rel in t["tablas"]:
            p.append(bloque_resultado(rel))
        if t.get("extra") == "quorum":
            p.append(
                "**Resumen por fase** (votos True por fuente de las ventanas de cada fase; `t2_3_resumen.csv`): A y B cumplen, C no.\n"
            )
            p.append(NOTA_FASE_C + "\n")
    p.append("## 3. Decisiones y desviaciones\n")
    p.append("Registro completo de `docs/DECISIONES_AUTONOMAS.md`:\n")
    p.append(leer(Path("docs/DECISIONES_AUTONOMAS.md")).strip() + "\n")
    p.append("## 4. Limitaciones con su evidencia\n")
    p.append(limitaciones() + "\n")
    p.append("## 5. Valores de configuración y sus citas\n")
    p.append(
        "`config/config.example.toml` (IP ocultas). Los comentarios contienen las citas de cada valor.\n"
    )
    p.append("```toml\n" + config_enmascarada().rstrip() + "\n```\n")
    p.append("### Parámetros calibrados del detector\n")
    p.append(parametros_detector())
    return "\n".join(p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--salida", type=Path, default=RAIZ / "informe" / "DATOS_PARA_REDACCION.md"
    )
    args = ap.parse_args(argv)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(generar(), encoding="utf-8")
    print(f"Escrito {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
