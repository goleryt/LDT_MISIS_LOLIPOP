"""Generate standalone CPU Kaggle notebook 21 for research gas-alarm triage."""

from __future__ import annotations

import json
from pathlib import Path

from generate_targets_v3_notebook import code_cell, markdown_cell

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / "notebooks" / "kaggle" / "21_gas_triage_audit_cpu.ipynb"
TAXONOMY = HERE / "config" / "state_taxonomy_v3.json"
EMBEDDED = {
    "event_panel_v3.py": HERE / "event_panel_v3.py",
    "event_panel_v3_kaggle.py": HERE / "event_panel_v3_kaggle.py",
    "gas_fingerprint_v4.py": HERE / "gas_fingerprint_v4.py",
    "gas_triage_v1.py": HERE / "gas_triage_v1.py",
}

INTRO = """# 21 · Исследовательский триаж газовых тревог (CPU, без обучения)

Метки описывают **гипотезы**, совместимые с поверкой или обслуживанием, но не подтверждают их. Инцидентных меток
нет. Тревоги не скрываются, backend и frozen G2 v3 не меняются. Результат и решение: `docs/GAS_TRIAGE_RESEARCH_RU.md`.

Выход: `results_21_gas_triage.json` и `summary_21_gas_triage_ru.md`, только агрегаты.
"""

HOW = """## Входы и запуск

1. Add Input: сырые `ext-journal-YYYY` и справочник каналов — те же источники, что у notebook 19.
2. Add Input: frozen output notebook 14 с `panel_manifest_v3.json` и parquet parts; SHA префикс `8cb6e0e2584f`.
3. Accelerator = None. Для проверки среды можно поставить `MODE = "SMOKE"` и выполнить Save & Run All.
4. Для результата по всем годам вернуть `MODE = "FULL"`, выполнить Save & Run All и скачать два итоговых файла.

FULL повторно читает архив: notebook 19 удалял временный секундный слой по умолчанию. На старте выводятся RAM,
свободное место и число бакетов. Полный прогон не запускается локально этим генератором.
"""

CONFIG = """# ЕДИНСТВЕННАЯ ЯЧЕЙКА, КОТОРУЮ МОЖНО МЕНЯТЬ
MODE = "FULL"  # "FULL" или "SMOKE"; SMOKE не сравним по числам
print("Режим:", MODE)
"""

ENV = """import os, sys, tempfile, warnings
from pathlib import Path
warnings.filterwarnings("ignore", category=UserWarning)
import numpy as np
import polars as pl
print("python", sys.version.split()[0], "| polars", pl.__version__, "| numpy", np.__version__)
"""

WRITE = """CODE_DIR = Path(tempfile.mkdtemp(prefix="ldt21_code_"))
for name, source in SOURCES.items():
    (CODE_DIR / name).write_text(source, encoding="utf-8")
(CODE_DIR / "state_taxonomy_v3.json").write_text(TAXONOMY_JSON, encoding="utf-8")
sys.path.insert(0, str(CODE_DIR))
import gas_triage_v1 as gt
print("Встроенный код записан:", ", ".join(sorted(SOURCES)))
"""

SELF_TEST = """# Короткая проверка причинного cutoff на синтетике перед чтением архива
from datetime import datetime, timedelta
t0 = datetime(2024, 12, 31, 23, 55)
def sec(ch, minute, value):
    return {"d_channel_key": ch, "d_object_key": "synthetic",
            "t": t0 + timedelta(minutes=minute), "mn": value, "mx": value}
synthetic = pl.DataFrame([sec("a", -1, 0.2), sec("a", 0, 1.4), sec("a", 4, 0.4),
                          sec("b", -1, 0.2), sec("b", 0, 1.4), sec("b", 4, 0.4)])
shapes = gt._event_shapes_for_bucket(pl, synthetic.sort("d_channel_key", "t"))
activity = synthetic.select("d_object_key", pl.col("t").dt.date().alias("day")).unique()
runs = gt.gf.bounded_silence_runs(pl, synthetic)
labeled = gt.label_events(shapes, activity, runs, t0 + timedelta(hours=1))
assert len(labeled) == 2 and all(e["other_ch_by_live_cutoff"] == 1 for e in labeled)
assert all(e["status_at_day_end"] == "pending_at_day_end" for e in labeled)
assert all(e["triage_retro"] == "censored_by_day" for e in labeled)
print("Синтетический cutoff: OK")
"""

PREFLIGHT = """CONFIG = gt.make_config_21(MODE, {"taxonomy_path": str(CODE_DIR / "state_taxonomy_v3.json")})
PREFLIGHT = gt.preflight(CONFIG)
print("Журналы:", PREFLIGHT["journal_years"])
print("Panel:", PREFLIGHT["panel_manifest_sha256"], "| строк:", PREFLIGHT["panel_rows"],
      "| частей:", PREFLIGHT["panel_parts"])
print("RAM GiB:", PREFLIGHT["ram_gib"], "| свободный диск GiB:", PREFLIGHT["free_stage_gib"],
      "| бакетов:", PREFLIGHT["channel_buckets"])
print(PREFLIGHT["staging_note"])
"""

RUN = """RESULT = gt.run_stage21(CONFIG)
print("Статус:", RESULT["status"], "| пересечений:", RESULT["crossings_total"],
      "| пауз:", RESULT["silence_runs"], "| время:", RESULT["runtime_s"], "с")
print("V1:", RESULT["v1_calendar"]["passed"], "| N1:", RESULT["n1_synchrony_control"]["passed"],
      "| backend gate:", RESULT["backend_gate"])
"""

SUMMARY = """from IPython.display import Markdown, display
OUT = Path(CONFIG["output_dir"])
display(Markdown((OUT / "summary_21_gas_triage_ru.md").read_text(encoding="utf-8")))
for name in ("results_21_gas_triage.json", "summary_21_gas_triage_ru.md"):
    p = OUT / name
    print("-", name, f"({p.stat().st_size / 1024:.1f} КБ)")
"""


def build_notebook() -> dict:
    sources = {name: path.read_text(encoding="utf-8") for name, path in EMBEDDED.items()}
    embed = "SOURCES = " + json.dumps(sources, ensure_ascii=False, indent=0) + "\n"
    taxonomy = "TAXONOMY_JSON = " + repr(TAXONOMY.read_text(encoding="utf-8")) + "\n"
    return {
        "cells": [markdown_cell(INTRO), markdown_cell(HOW), code_cell(CONFIG), code_cell(ENV),
                  markdown_cell("## Встроенный код\n"), code_cell(embed), code_cell(taxonomy), code_cell(WRITE),
                  code_cell(SELF_TEST),
                  markdown_cell("## Preflight\n"), code_cell(PREFLIGHT),
                  markdown_cell("## Триаж\n"), code_cell(RUN),
                  markdown_cell("## Агрегатная сводка\n"), code_cell(SUMMARY)],
        "metadata": {"kaggle": {"accelerator": "none", "dataSources": [], "isInternetEnabled": False,
                                  "language": "python", "sourceType": "notebook", "isGpuEnabled": False},
                     "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python"}},
        "nbformat": 4, "nbformat_minor": 5,
    }


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_notebook(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("written", OUTPUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
