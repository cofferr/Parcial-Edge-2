"""Tarea 2.1: auditoría de superficie de ataque con nmap (docs/DISENO.md §26).

    uv run python scripts/t2_1_auditoria.py --fase tcp        # TCP completo, sin privilegios
    uv run python scripts/t2_1_auditoria.py --fase udp --run-id <run_id>   # pide sudo
    uv run python scripts/t2_1_auditoria.py --fase analizar --run-id <run_id>
    uv run python scripts/t2_1_auditoria.py                   # tcp + udp + análisis

Objetivos: SOLO los de la config (ESP32-CAM, DroidCam y el IP del propio host en la
interfaz del hotspot). Nada de barridos de subred. La ESP32-CAM admite un solo cliente:
no tengas otro cliente abierto (navegador, stream, DroidCam no aplica) durante el escaneo.
El UDP (-sU) necesita root: este script llama a `sudo nmap` y te pedirá la contraseña.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

import pandas as pd

from edge_parcial import metadata
from edge_parcial.analysis import auditoria as aud
from edge_parcial.analysis.tablas import escribir_tabla
from edge_parcial.config import RAIZ, RUTA_CONFIG, ErrorConfig, cargar_config

DISPOSITIVOS = ("esp32", "droidcam", "host")
COMANDO_BREW = "brew install nmap"
# Parámetros fijos pedidos (docs/DISENO.md §26). --max-rate solo en la ESP32-CAM.
ARGS_TCP = [
    "-p-",
    "-Pn",
    "-sT",
    "--open",
    "-sV",
    "--version-light",
    "--max-retries",
    "1",
]
ARGS_UDP = ["-sU", "--top-ports", "50", "-Pn", "--open", "--max-retries", "1"]
MAX_RATE_ESP32 = "300"


def ip_del_host(gateway_ip: str, config: Path) -> str:
    """IP del Mac en la interfaz que lleva al gateway del hotspot (o [auditoria].host_ip)."""
    with open(config, "rb") as f:
        manual = tomllib.load(f).get("auditoria", {}).get("host_ip")
    if manual:
        return str(manual)
    ruta = subprocess.run(
        ["route", "-n", "get", gateway_ip],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    iface = next(
        (ln.split(":")[1].strip() for ln in ruta.splitlines() if "interface:" in ln),
        None,
    )
    if not iface:
        raise RuntimeError(
            f"No se pudo hallar la interfaz hacia {gateway_ip}; define [auditoria] host_ip"
        )
    ip = subprocess.run(
        ["ipconfig", "getifaddr", iface],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if not ip:
        raise RuntimeError(f"La interfaz {iface} no tiene IP")
    return ip


def estado_esp32(cfg, etiqueta: str, registro: list) -> dict:
    r = metadata.consultar_status_esp32(cfg.esp32.ip, cfg.esp32.puerto)
    r = {"momento": etiqueta, **r}
    registro.append(r)
    print(
        f"  /status ESP32 [{etiqueta}]: {'ok fw=' + str(r['fw']) if r['ok'] else r['error']}"
    )
    return r


def escanear(ejecutar, ip: str, args: list[str], base: Path, con_sudo: bool) -> int:
    cmd = ["nmap", *args, "-oX", f"{base}.xml", "-oN", f"{base}.txt", ip]
    if con_sudo and os.geteuid() != 0:
        cmd = ["sudo", *cmd]
    print("  $", " ".join(cmd))
    return ejecutar(cmd).returncode


def cargar_json(ruta: Path) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else {}


def fase_escaneo(cfg, ips, fase, carpeta, aud_json, ejecutar, solo, sondear):
    """Una fase (tcp|udp) sobre los objetivos. Devuelve lo registrado en aud_json."""
    objetivos = [d for d in DISPOSITIVOS if d in solo]
    for d in objetivos:
        print(f"[{fase}] {d} ({ips[d]})")
        if d == "esp32":
            antes = estado_esp32(cfg, f"antes-{fase}", aud_json["esp32_status"])
            if not antes["ok"]:
                print(
                    "  ESP32 no responde: se omite (ver docs/CHECKLIST_HARDWARE_P2.md)"
                )
                aud_json["omitidos"].append(f"esp32-{fase}: /status no responde antes")
                continue
        args = ARGS_TCP if fase == "tcp" else ARGS_UDP
        if d == "esp32":
            args = [*args, "--max-rate", MAX_RATE_ESP32]
        rc = escanear(
            ejecutar, ips[d], args, carpeta / f"nmap_{d}_{fase}", fase == "udp"
        )
        aud_json["escaneos"][f"{d}_{fase}"] = {"returncode": rc, "args": args}
        if rc != 0:
            aud_json["omitidos"].append(f"{d}-{fase}: nmap terminó con código {rc}")
        if d == "esp32":
            despues = estado_esp32(cfg, f"despues-{fase}", aud_json["esp32_status"])
            aud_json["esp32_dejo_de_responder"] |= not despues["ok"]
            if despues["ok"] and antes["fw"] != despues["fw"]:
                aud_json["esp32_fw_cambio"] = True
    if fase == "tcp" and "host" in objetivos:
        lsof = ejecutar(
            ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], capture_output=True, text=True
        ).stdout
        (carpeta / "host_lsof.txt").write_text(lsof, encoding="utf-8")
    if fase == "tcp":
        for d in ("esp32", "droidcam"):
            xml = carpeta / f"nmap_{d}_tcp.xml"
            if d not in objetivos or not xml.is_file():
                continue
            for fila in aud.parsear_nmap_xml(xml, "tcp"):
                if fila["estado"] == "open" and aud.es_candidato_http(fila):
                    obs = sondear(ips[d], fila["puerto"])
                    aud_json["sondeos"][f"{d}:{fila['puerto']}"] = obs


def analizar(carpeta: Path, aud_json: dict, salida: Path) -> None:
    por_dispositivo: dict[str, list[dict]] = {
        "esp32": [],
        "droidcam": [],
        "local": [],
        "host": [],
    }
    for d in ("esp32", "droidcam"):
        for fase in ("tcp", "udp"):
            xml = carpeta / f"nmap_{d}_{fase}.xml"
            if not xml.is_file():
                continue
            for f in aud.parsear_nmap_xml(xml, fase):
                obs = aud_json.get("sondeos", {}).get(f"{d}:{f['puerto']}", [])
                f["observaciones"] = "; ".join(obs)
                por_dispositivo[d].append(f)
    nmap_host = []
    for fase in ("tcp", "udp"):
        xml = carpeta / f"nmap_host_{fase}.xml"
        if xml.is_file():
            nmap_host += aud.parsear_nmap_xml(xml, fase)
    lsof = carpeta / "host_lsof.txt"
    escuchas = (
        aud.parsear_lsof(lsof.read_text(encoding="utf-8")) if lsof.is_file() else []
    )
    por_dispositivo["host"] = aud.interfaces_host(escuchas, nmap_host)
    tabla = aud.tabla_interfaces(por_dispositivo)
    escribir_tabla(
        tabla,
        salida / "t2_1_interfaces",
        caption="Tabla I: interfaces expuestas por dispositivo",
        label="tab:t2_1_I",
        decimales=0,
    )
    a = aud.calcular_as(tabla, ["esp32", "droidcam", "local"], "a_tres_fuentes")
    b = aud.calcular_as(tabla, ["esp32", "droidcam", "local", "host"], "b_con_host")
    escribir_tabla(
        pd.concat([a, b], ignore_index=True),
        salida / "t2_1_as",
        caption="Superficie de ataque AS = N x I",
        label="tab:t2_1_AS",
        decimales=3,
    )
    faltan = [
        f for f in ("tcp", "udp") if not (carpeta / f"nmap_esp32_{f}.xml").is_file()
    ]
    print(f"Tablas en {salida} (fases sin datos de la ESP32: {faltan or 'ninguna'}).")
    print(pd.concat([a, b], ignore_index=True).to_string(index=False))


def main(
    argv: list[str] | None = None,
    *,
    ejecutar=subprocess.run,
    sondear=aud.sondear_http,
    ips=None,
) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument(
        "--fase", choices=("tcp", "udp", "analizar", "todo"), default="todo"
    )
    ap.add_argument(
        "--run-id", help="continúa una auditoría existente (data/raw/<run_id>)"
    )
    ap.add_argument(
        "--solo", default=",".join(DISPOSITIVOS), help="subconjunto de objetivos"
    )
    ap.add_argument("--config", type=Path, default=RUTA_CONFIG)
    ap.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw")
    ap.add_argument("--salida", type=Path, default=RAIZ / "data" / "processed")
    args = ap.parse_args(argv)
    if shutil.which("nmap") is None and ejecutar is subprocess.run:
        print(
            f"nmap no está instalado. Instálalo con:\n  {COMANDO_BREW}", file=sys.stderr
        )
        return 2
    try:
        cfg = cargar_config(args.config)
        ips = ips or {
            "esp32": cfg.esp32.ip,
            "droidcam": cfg.droidcam.ip,
            "host": ip_del_host(cfg.gateway_ip, args.config),
        }
    except (ErrorConfig, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    solo = {s.strip() for s in args.solo.split(",") if s.strip()}
    if solo - set(DISPOSITIVOS):
        print(f"Objetivos inválidos: {solo - set(DISPOSITIVOS)}", file=sys.stderr)
        return 2
    run_id = args.run_id or f"{datetime.now():%Y%m%d-%H%M%S}-auditoria"
    carpeta = args.raw / run_id
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta_json = carpeta / "auditoria.json"
    aud_json = cargar_json(ruta_json)
    for k, v in (
        ("esp32_status", []),
        ("escaneos", {}),
        ("sondeos", {}),
        ("omitidos", []),
        ("esp32_dejo_de_responder", False),
        ("esp32_fw_cambio", False),
    ):
        aud_json.setdefault(k, v)
    aud_json["run_id"], aud_json["ips"] = run_id, ips
    print(f"Auditoría {run_id}; objetivos: {ips}")
    for fase in ("tcp", "udp"):
        if args.fase in (fase, "todo"):
            fase_escaneo(cfg, ips, fase, carpeta, aud_json, ejecutar, solo, sondear)
            ruta_json.write_text(
                json.dumps(aud_json, indent=2, ensure_ascii=False), encoding="utf-8"
            )
    if args.fase in ("analizar", "todo", "tcp", "udp"):
        analizar(carpeta, aud_json, args.salida)
    if aud_json["esp32_dejo_de_responder"]:
        print("AVISO: la ESP32-CAM dejó de responder tras un escaneo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
