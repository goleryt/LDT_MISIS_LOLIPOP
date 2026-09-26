"""Generate standalone CPU Kaggle notebook 19 (gas crossing fingerprint diagnostics)."""

from __future__ import annotations

import json
from pathlib import Path

from generate_targets_v3_notebook import code_cell, markdown_cell

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / "notebooks" / "kaggle" / "19_gas_fingerprint_diagnostics_cpu.ipynb"
TAXONOMY = HERE / "config" / "state_taxonomy_v3.json"
EMBEDDED = {
    "event_panel_v3.py": HERE / "event_panel_v3.py",
    "event_panel_v3_kaggle.py": HERE / "event_panel_v3_kaggle.py",
    "gas_fingerprint_v4.py": HERE / "gas_fingerprint_v4.py",
}

INTRO = """# 19 · Диагностика отпечатка газовых пересечений (CPU, без обучения)

Ноутбук описывает наблюдаемые строгие пересечения 1 % CH4 и проверяет, достаточно ли положительных примеров вне
окон **подозреваемого обслуживания** для отдельной спецификации stage 20. Это не прогноз и не доказательство
поверки, утечки или физического инцидента. Frozen G2 v3 не изменяется.

Выходы содержат только агрегаты: `results_19_gas_fingerprint.json` и `summary_19_gas_fingerprint_ru.md`.
"""

HOW = """## Входы и запуск

1. Add Input: сырые `ext-journal-YYYY` и справочник каналов — те же источники, что у notebook 14.
2. Add Input: frozen output notebook 14 с `panel_manifest_v3.json` и parquet parts. Manifest обязан начинаться с
   `8cb6e0e2584f`; другой panel останавливает прогон.
3. Accelerator = None. Сначала `SMOKE`, затем `FULL` → Save & Run All.
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

WRITE = """CODE_DIR = Path(tempfile.mkdtemp(prefix="ldt19_code_"))
for name, text in SOURCES.items():
    (CODE_DIR / name).write_text(text, encoding="utf-8")
(CODE_DIR / "state_taxonomy_v3.json").write_text(TAXONOMY_JSON, encoding="utf-8")
sys.path.insert(0, str(CODE_DIR))
import gas_fingerprint_v4 as gf
print("Встроенный код записан:", ", ".join(sorted(SOURCES)))
"""

PREFLIGHT = """CONFIG = gf.make_config_19(MODE, {"taxonomy_path": str(CODE_DIR / "state_taxonomy_v3.json")})
PREFLIGHT = gf.preflight_sources(CONFIG)
print("Журналы:", PREFLIGHT["journal_years"])
print("Panel:", PREFLIGHT["panel_manifest_sha256"], "| строк:", PREFLIGHT["panel_rows"], "| частей:", PREFLIGHT["panel_parts"])
"""

RUN = """RESULT = gf.run_stage19(CONFIG)
print("Статус:", RESULT["status"], "| пересечений:", RESULT["crossings_total"], "| время:", RESULT["runtime_s"], "с")
"""

SUMMARY = """from IPython.display import Markdown, display
OUT = Path(CONFIG["output_dir"])
display(Markdown((OUT / "summary_19_gas_fingerprint_ru.md").read_text(encoding="utf-8")))
for name in ("results_19_gas_fingerprint.json", "summary_19_gas_fingerprint_ru.md"):
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
                  markdown_cell("## Preflight\n"), code_cell(PREFLIGHT),
                  markdown_cell("## Диагностика\n"), code_cell(RUN),
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

