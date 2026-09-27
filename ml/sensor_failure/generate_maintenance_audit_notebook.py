"""Generate the standalone CPU Kaggle notebook 17 (read-only audit of the delivered gas bundle by maintenance windows)."""

from __future__ import annotations

import json
from pathlib import Path

from generate_targets_v3_notebook import code_cell, markdown_cell

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / "notebooks" / "kaggle" / "17_gas_maintenance_audit_cpu.ipynb"
EMBEDDED = {"target_models_v3_runtime.py": HERE / "target_models_v3_runtime.py",
            "maintenance_audit_v3.py": HERE / "maintenance_audit_v3.py"}

INTRO = """# 17 v2 · Audit газового bundle внутри и вне окон сервисных работ (CPU, без обучения)

**v2 (Drive 46):** preflight панели против bundle; молчание только между двумя реальными показаниями;
окна по индексу строки; тревоги G2 и R1 на одной eligible-когорте; контрольные окна не пересекаются с основным.

**Accelerator = None**, интернет не нужен. Ничего не обучается и не выбирается; bundle не меняется.

Вопрос: насколько качество переданной модели G2 (прогноз пересечения газа 1 % в D+2) держится **вне** периодов,
когда датчики снимали на поверку / проверяли газовой смесью. Спецификация согласована с GPT (Drive 38–44):
- скорится **неизменённый** `gas_cross_v3_bundle` и правило R1 на **одних и тех же** строках;
- окна работ по данным: все газовые каналы объекта молчат ≥ 4 суток → окно [начало − 3; конец + 21]
  (**post-hoc**, использует будущее — только для исследования меток; чувствительность +14 / +30);
- **причинный** флаг на D: такое молчание закончилось в последние 21 сутки и датчики уже вернулись;
- **negative control**: те же окна, сдвинутые на +30 и +60 суток;
- метрики по стратам: counts, unknown, prevalence, PR-AUC и **lift** G2 и R1, Brier/ECE, бутстрэп по неделям ΔPR-AUC;
  тревоги — **одна общая** политика top-25/сутки с cooldown, разбитая по стратам;
- периоды 2025 H2 и 2026 H1 — **ретроспективный** audit (оба уже исследовались), не нетронутый тест.

Выход: `results_17_maintenance_audit.json`, `summary_17_maintenance_audit_ru.md` — только агрегаты.
"""

HOW = """## Как запустить

1. **Add Input** → выход ноутбука 14 **той же версии, на которой обучался 16** (не перезапуск с исправлениями
   same-second). Если панель другая, ноутбук остановится с `PanelMismatch` и покажет найденный хеш — не обходить.
2. **Add Input** → dataset с двумя файлами: `gas_cross_v3_bundle.zip` и `gas_cross_v3_bundle.zip.sha256`
   (ровно те, что переданы backend; SHA сверяется автоматически).
3. **Accelerator → None**, `MODE = "FULL"` → **Save Version → Save & Run All** (минуты).
"""

CONFIG = """# ЕДИНСТВЕННАЯ ЯЧЕЙКА, КОТОРУЮ МОЖНО ИЗМЕНЯТЬ
MODE = "FULL"   # "FULL" или "SMOKE" (1/10 каналов, проверка запуска)
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
CODE_DIR = Path(tempfile.mkdtemp(prefix="ldt17_code_"))
for name, text in SOURCES.items():
    (CODE_DIR / name).write_text(text, encoding="utf-8")
sys.path.insert(0, str(CODE_DIR))
import maintenance_audit_v3 as ma
print("код записан:", ", ".join(sorted(SOURCES)))
"""

RUN = """CONFIG = ma.make_config_17(MODE)
RESULT = ma.run_audit_17(CONFIG)
print("Статус:", RESULT["status"], "| время:", RESULT["runtime_s"], "с")
"""

SUMMARY = """from IPython.display import Markdown, display
OUT = Path(CONFIG["output_dir"])
display(Markdown((OUT / "summary_17_maintenance_audit_ru.md").read_text(encoding="utf-8")))
for name in ("results_17_maintenance_audit.json", "summary_17_maintenance_audit_ru.md"):
    p = OUT / name
    print("-", name, f"({p.stat().st_size / 1024:.0f} КБ)" if p.exists() else "— НЕ СОЗДАН")
"""


def build_notebook() -> dict:
    sources = {name: path.read_text(encoding="utf-8") for name, path in EMBEDDED.items()}
    embed = "# Исходный код (репозиторий на Kaggle не нужен)\nSOURCES = " + json.dumps(sources, ensure_ascii=False, indent=0) + "\n"
    return {
        "cells": [markdown_cell(INTRO), markdown_cell(HOW), code_cell(CONFIG), code_cell(ENV),
                  markdown_cell("## Встроенный код\n\nRuntime 15 и audit 17 — те же файлы, что в `ml/sensor_failure/`. "
                                "Predictor и модель берутся из подключённого bundle.\n"),
                  code_cell(embed), code_cell(WRITE),
                  markdown_cell("## Прогон (только скоринг)\n"), code_cell(RUN),
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
