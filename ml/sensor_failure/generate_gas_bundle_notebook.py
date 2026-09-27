"""Generate the standalone CPU Kaggle notebook 16 (final G2 gas-cross train + executable backend bundle)."""

from __future__ import annotations

import json
from pathlib import Path

from generate_targets_v3_notebook import code_cell, markdown_cell

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / "notebooks" / "kaggle" / "16_gas_bundle_v3_cpu.ipynb"
EMBEDDED = {
    "target_models_v3_runtime.py": HERE / "target_models_v3_runtime.py",
    "gas_bundle_v3.py": HERE / "gas_bundle_v3.py",
    "gas_predictor_v3.py": HERE / "gas_predictor_v3.py",
    "event_panel_v3.py": HERE / "event_panel_v3.py",
    "config/state_taxonomy_v3.json": HERE / "config" / "state_taxonomy_v3.json",
}

INTRO = """# 16 · Финальный газовый прогноз v3: единственный train и bundle для backend (CPU)

**Вычисления:** CPU, **Accelerator = None**, интернет не нужен. Вход — выход ноутбука 14 (как у 15).

Что делает (решения зафиксированы до запуска, Drive 22–27, `docs/EXPORT_16_GAS_BUNDLE_V3_RU.md`):
- обучает **одну** модель — `G2_no_calendar` для `target_t4_gas_cross` (наблюдаемое строгое пересечение газа 1 %
  снизу вверх в [D+2; D+3)); признаки, гиперпараметры и выборка — ровно как в 15;
- рецепт `RECIPE` задаётся до запуска и не выбирается по результатам:
  - `refit_2025h1` — train до конца 2024, Platt на 2025 H1, однократный audit 2025 H2;
  - `fold_2024_exact` — точное воспроизведение fold_2024 из 15 (audit = 2024 H2);
- если в калибровке < 30 известных положительных — остановка **до** обучения (решение о рецепте — за Дашей);
- сверяет код с прогоном 15 (PR-AUC G2 fold_2024; для refit это отдельное сверочное обучение fold_2024 **до**
  финального) — в выборе не участвует, но расхождение > 0,001 **останавливает прогон без bundle** (fail-closed);
- упаковывает **исполняемый bundle без pickle**: `model.txt` (LightGBM), `bundle.json` (Platt, контракт, eligibility),
  `predictor.py`, код признаков 14 (`features_v3/`), контракт, синтетический пример, requirements, SHA-256;
- проверяет bundle, загруженный из файлов, против модели в памяти (parity), SHA всех файлов, обязательную дату среза,
  контракт и latency; при непройденной приёмке bundle удаляется. SHA-256 ZIP — отдельным файлом рядом с ZIP.

Это **proxy_score в shadow-режиме**: не вероятность пожара и не подтверждённый инцидент; `operational_ready = false`.
В выходных файлах нет ключей каналов и построчных прогнозов.
"""

HOW = """## Как запустить

1. **Add Input** → выход ноутбука 14 (тот же, что подключали к 15).
2. **Settings → Accelerator → None.**
3. Проверить `RECIPE` в следующей ячейке (одно значение — один прогон).
4. `MODE = "SMOKE"` — ≈1/10 каналов, несколько минут, результат не для backend. `MODE = "FULL"` → **Save Version → Save & Run All**.
5. Скачать из Output: `gas_cross_v3_bundle.zip`, `gas_cross_v3_bundle.zip.sha256`, `results_export_16_v3.json`,
   `summary_export_16_v3_ru.md`. Статус ≠ `completed` → bundle backend не передавать.
"""

CONFIG = """# ЕДИНСТВЕННАЯ ЯЧЕЙКА, КОТОРУЮ МОЖНО ИЗМЕНЯТЬ
MODE = "FULL"             # "FULL" или "SMOKE"
RECIPE = "refit_2025h1"   # "refit_2025h1" или "fold_2024_exact" — решение до запуска, не по audit
print("Режим:", MODE, "| рецепт:", RECIPE)
"""

ENV = """import os, platform, warnings
warnings.filterwarnings("ignore", category=UserWarning)
import numpy, pandas, polars, sklearn, lightgbm
for m in (numpy, pandas, polars, sklearn, lightgbm):
    print(f"{m.__name__:10s}", m.__version__)
print("CPU       ", os.cpu_count())
"""

WRITE = """import sys, tempfile
from pathlib import Path
CODE_DIR = Path(tempfile.mkdtemp(prefix="ldt16_code_"))
for name, text in SOURCES.items():
    p = CODE_DIR / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
sys.path.insert(0, str(CODE_DIR))
os.environ["LDT_CODE_DIR"] = str(CODE_DIR)
import gas_bundle_v3 as gb
import target_models_v3_runtime as rt
print("код записан:", ", ".join(sorted(SOURCES)))
"""

SELF = """SELF_TESTS = gb.run_export_self_tests(Path(tempfile.mkdtemp()))
for name, ok in SELF_TESTS.items():
    print("OK  " if ok else "FAIL", name)
assert all(SELF_TESTS.values()), "Самопроверки не пройдены"
"""

RUN = """CONFIG = gb.make_config_export(MODE, RECIPE)
try:
    RESULT = gb.run_export_v3(CONFIG)
except gb.RecipeStop as stop:
    print("ОСТАНОВКА ДО ОБУЧЕНИЯ:", stop)
    raise
except gb.ReleaseBlocked as blocked:
    print("RELEASE GATE НЕ ПРОЙДЕН — bundle не выдаётся:", blocked)
    raise
print()
print("Статус:", RESULT["status"], "| время:", RESULT["runtime_s"], "с")
print("Сверка с 15:", RESULT["reproduction_15"])
assert RESULT["acceptance"]["passed"], "Приёмка bundle не пройдена — bundle не передавать"
"""

SUMMARY = """from IPython.display import Markdown, display
OUT = Path(CONFIG["output_dir"])
display(Markdown((OUT / "summary_export_16_v3_ru.md").read_text(encoding="utf-8")))
"""

FINISH = """print("Файлы для backend и команды:")
for name in ("gas_cross_v3_bundle.zip", "gas_cross_v3_bundle.zip.sha256", "results_export_16_v3.json", "summary_export_16_v3_ru.md"):
    p = OUT / name
    print("-", name, f"({p.stat().st_size / 1024:.0f} КБ)" if p.exists() else "— НЕ СОЗДАН")
print("Построчные прогнозы и идентификаторы не сохраняются.")
"""


def build_notebook() -> dict:
    sources = {name: path.read_text(encoding="utf-8") for name, path in EMBEDDED.items()}
    embed = "# Исходный код ML (репозиторий на Kaggle не нужен): записывается в каталог и импортируется\n"
    embed += "SOURCES = " + json.dumps(sources, ensure_ascii=False, indent=0) + "\n"
    return {
        "cells": [
            markdown_cell(INTRO), markdown_cell(HOW), code_cell(CONFIG), code_cell(ENV),
            markdown_cell("## Встроенный код\n\nRuntime 15, экспорт 16, predictor и код признаков 14 — те же файлы, "
                          "что в репозитории (`ml/sensor_failure/`).\n"),
            code_cell(embed), code_cell(WRITE),
            markdown_cell("## Самопроверки на синтетике\n\nОба рецепта, приёмка bundle, остановка при нехватке "
                          "положительных, отсутствие ключей каналов в выходах.\n"),
            code_cell(SELF),
            markdown_cell("## Единственный прогон: обучение, audit, bundle, приёмка\n"),
            code_cell(RUN),
            markdown_cell("## Сводка\n"),
            code_cell(SUMMARY),
            code_cell(FINISH),
        ],
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python"}},
        "nbformat": 4, "nbformat_minor": 5,
    }


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_notebook(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("written", OUTPUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
