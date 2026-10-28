"""Tarea 2.3: la prueba guiada completa con fuentes simuladas, y el resumen por fase."""

import importlib.util
import sys

import pandas as pd

from edge_parcial.config import RAIZ, RUTA_EJEMPLO
from edge_parcial.edge.detector import ParamsDetector
from edge_parcial.nucleo import config_p2
from edge_parcial.nucleo import prueba_quorum as pq

S = 1_000_000_000


def cargar_script():
    espec = importlib.util.spec_from_file_location(
        "t2_3", RAIZ / "scripts" / "t2_3_prueba_quorum.py"
    )
    mod = importlib.util.module_from_spec(espec)
    sys.modules["t2_3"] = mod
    espec.loader.exec_module(mod)
    return mod


def test_resumir_fases_cuenta_votos_y_aplica_la_guarda():
    filas = []
    for k in range(10):  # ventanas de 1 s desde t=0
        filas.append(
            {
                "ventana": k,
                "t_ventana_ini_ns": k * S,
                "voto_esp32": 1,
                "voto_droidcam": int(k % 2 == 0),
                "voto_local": 0,
                "alerta": int(k % 2 == 0),
            }
        )
    tiempos = [
        {
            "fase": "A",
            "descripcion": "d",
            "tapadas": (),
            "debe_alertar": True,
            "t_ini_ns": 0,
            "t_fin_ns": 10 * S,
        },
        {
            "fase": "C",
            "descripcion": "d",
            "tapadas": ("esp32", "droidcam"),
            "debe_alertar": False,
            "t_ini_ns": 0,
            "t_fin_ns": 10 * S,
        },
    ]
    r = pq.resumir_fases(pd.DataFrame(filas), tiempos, guarda_s=4, ventana_s=1.0)
    a = r.iloc[0]
    assert a.ventanas == 6  # ventanas 4..9
    assert (a.votos_true_esp32, a.votos_true_droidcam, a.votos_true_local) == (6, 3, 0)
    assert a.alertas == 3 and bool(a.cumple)
    assert not bool(r.iloc[1].cumple)  # la fase C no debía tener alertas


def test_prueba_completa_simulada(tmp_path):
    mod = cargar_script()
    cfg = tmp_path / "config.toml"
    cfg.write_text(RUTA_EJEMPLO.read_text(encoding="utf-8"), encoding="utf-8")
    config_p2.escribir_secciones_detector(
        cfg, {f: ParamsDetector(32.0, 0.01, 0.3) for f in config_p2.FUENTES}
    )
    rc = mod.main(
        [
            "--simular", "--fase-s", "5", "--cuenta-s", "1", "--calentamiento-s", "2",
            "--guarda-s", "2.5", "--config", str(cfg), "--raw", str(tmp_path / "raw"),
            "--salida", str(tmp_path / "proc"), "--docs", str(tmp_path / "docs"),
        ]
    )  # fmt: skip
    assert rc == 0
    resumen = pd.read_csv(tmp_path / "proc" / "t2_3_sim_resumen.csv")
    assert list(resumen["fase"]) == ["A", "B", "C"]
    assert resumen["cumple"].all()
    c = resumen.iloc[2]
    assert c["alertas"] == 0 and c["votos_true_local"] > 0
    assert (tmp_path / "docs" / "T2_3_SIM_RESULTADOS.md").is_file()
    logs = list((tmp_path / "docs" / "evidencia").glob("t2_3_sim_consola_*.log"))
    assert logs and "ALERTA" in logs[0].read_text(encoding="utf-8")


def test_argumentos_invalidos(tmp_path, capsys):
    mod = cargar_script()
    assert mod.main(["--simular", "--tapa-b", "esp32,local"]) == 2
