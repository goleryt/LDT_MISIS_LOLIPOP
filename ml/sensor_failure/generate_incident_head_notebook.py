"""Generate the standalone CPU Kaggle notebook 18 (incident head trained on an incident register; stub for now)."""

from __future__ import annotations

import json
from pathlib import Path

from generate_targets_v3_notebook import code_cell, markdown_cell

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / "notebooks" / "kaggle" / "18_incident_head_stub_cpu.ipynb"
EMBEDDED = {"target_models_v3_runtime.py": HERE / "target_models_v3_runtime.py",
            "incident_predictor_v1.py": HERE / "incident_predictor_v1.py",
            "incident_head_v1.py": HERE / "incident_head_v1.py"}

INTRO = """# 18 · Прогноз инцидентов по реестру: модуль + заглушка реестра (CPU)

**Accelerator = None**, интернет не нужен. Газовый bundle G2 не меняется.

Подтверждённых пожаров, подтоплений и НСД в данных нет; организаторы разрешили заглушки, если показано, что на реальных
данных решение заработает. Ноутбук:
- агрегирует панель 14 до объект × сутки (признаки на конец D);
- строит **заглушку реестра** на реальных сутках: инцидент тем вероятнее, чем сильнее сработали профильные датчики
  объекта в **сами сутки инцидента**; модель видит только данные ≤ D, окно прогноза [D+2; D+3);
- четыре заранее заданные силы связи: β = 0 (контроль — модель обязана НЕ обогнать правило), 1, 2 (основная), 3;
- обучает LightGBM + Platt по времени (train до 2025, калибровка 2025 H1, проверка 2025 H2), сравнивает с правилом
  «профильные тревоги за 7 суток», применяет пороги допуска, строит кривую обучения по числу инцидентов;
- выпускает `incident_head_bundle.zip` + `.sha256` (без pickle) и файлы заглушки для backend.

Цифры — **демо конвейера (evidence E4)**, не качество на реальных инцидентах. Контракт:
`docs/INCIDENT_REGISTER_CONTRACT_RU.md`.
"""

HOW = """## Как запустить

1. **Add Input** → выход ноутбука 14 (та же версия, что для 16/17).
2. **Accelerator → None**, `MODE = "FULL"` → **Save Version → Save & Run All**.
3. Скачать из Output: `results_18_incident_head.json`, `summary_18_incident_head_ru.md`,
   `incident_head_bundle.zip`, `incident_head_bundle.zip.sha256`, `incident_register_stub.csv`,
   `incident_register_coverage_stub.json`.
"""

CONFIG = """# ЕДИНСТВЕННАЯ ЯЧЕЙКА, КОТОРУЮ МОЖНО ИЗМЕНЯТЬ
MODE = "FULL"   # "FULL" или "SMOKE" (1/4 объектов, проверка запуска)
print("Режим:", MODE)
"""

ENV = """import os, warnings
warnings.filterwarnings("ignore", category=UserWarning)
import numpy, pandas, polars, sklearn, lightgbm, sys
for m in (numpy, pandas, polars, sklearn, lightgbm):
    print(f"{m.__name__:10s}", m.__version__)
print("python    ", sys.version.split()[0])
"""

WRITE = """import tempfile
from pathlib import Path
CODE_DIR = Path(tempfile.mkdtemp(prefix="ldt18_code_"))
for name, text in SOURCES.items():
    (CODE_DIR / name).write_text(text, encoding="utf-8")
sys.path.insert(0, str(CODE_DIR))
import incident_head_v1 as ih
print("код записан:", ", ".join(sorted(SOURCES)))
"""

RUN = """CONFIG = ih.make_config_18(MODE)
RESULT = ih.run_incident_head(CONFIG)
print("Статус:", RESULT["status"], "| время:", RESULT["runtime_s"], "с")
"""

SUMMARY = """from IPython.display import Markdown, display
OUT = Path(CONFIG["output_dir"])
display(Markdown((OUT / "summary_18_incident_head_ru.md").read_text(encoding="utf-8")))
for name in ("results_18_incident_head.json", "summary_18_incident_head_ru.md", "incident_head_bundle.zip",
             "incident_head_bundle.zip.sha256", "incident_register_stub.csv", "incident_register_coverage_stub.json"):
    p = OUT / name
    print("-", name, f"({p.stat().st_size / 1024:.0f} КБ)" if p.exists() else "— НЕ СОЗДАН")
"""


def build_notebook() -> dict:
    sources = {name: path.read_text(encoding="utf-8") for name, path in EMBEDDED.items()}
    embed = "# Исходный код (репозиторий на Kaggle не нужен)\nSOURCES = " + json.dumps(sources, ensure_ascii=False, indent=0) + "\n"
    return {
        "cells": [markdown_cell(INTRO), markdown_cell(HOW), code_cell(CONFIG), code_cell(ENV),
                  markdown_cell("## Встроенный код\n\nТе же файлы, что в `ml/sensor_failure/`.\n"),
                  code_cell(embed), code_cell(WRITE),
                  markdown_cell("## Прогон\n"), code_cell(RUN),
                  markdown_cell("## Сводка\n"), code_cell(SUMMARY)],
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python"}},
        "nbformat": 4, "nbformat_minor": 5,
    }


def main() -> None:
    OUTPUT.write_text(json.dumps(build_notebook(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("written", OUTPUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
