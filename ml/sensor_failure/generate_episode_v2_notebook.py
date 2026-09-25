"""Generate the standalone CPU Kaggle notebook 13 (strict onset target v2 + cadence features)."""

from __future__ import annotations

import json
from pathlib import Path

from generate_pre2025_audit_notebook import code_cell, markdown_cell


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / "notebooks" / "kaggle" / "13_failure_onset_v2_cadence_cpu.ipynb"

INTRO = """# 13 · Основная цель v2: строгий onset и cadence-признаки (CPU)

**Вычисления:** CPU, в Kaggle выбрать **Accelerator = None**. Вход — тот же приватный dataset panel v2, что у 01–06.

План и гипотезы зафиксированы до обучения: `docs/EXPERIMENT_13_EPISODE_V2_RU.md` (шаги 1–4 раздела 9
`docs/ML_TZ_BEST_FIT_SOLUTION_RU.md`).

**Цель v2** `failure_state_strict_onset_Dplus2_proxy_v2`: наблюдаемый proxy **начала** эпизода `Неисправен`/`Обесточен`
ровно в D+2. От цели v1 отличается одним правилом: строки, где у канала в D+1 было failure-событие, получают `null`
(эпизод начался раньше D+2). Строится из panel v2, архив заново не сканируется. Это не подтверждённая поломка.

| эксперимент | один изменяемый фактор |
|---|---|
| E1 | цель v1 → v2 (признаки M0 без календаря), лестница B0–B4 и LightGBM на v2 |
| E2 | + cadence-признаки (окна 7 и 30 суток по наблюдаемым строкам канала) |
| E3 | − recurrence при наличии cadence |

Фолды, метрики, эпизоды (50 каналов/сутки, cooldown 72 ч), парный бутстрэп блоками недель и gates — из ноутбука 05,
без изменений. 2025 H2 и 2026 не загружаются. Результаты: `results_failure_onset_v2.json`,
`summary_failure_onset_v2_ru.md` (только агрегаты).
"""

HOW = """## Как запустить

1. **Add Input** → приватный dataset с `panel_manifest_v2.json`.
2. **Accelerator → None.**
3. `MODE = "SMOKE"` для проверки (≈1/20 каналов, результаты `non_comparable`), затем `MODE = "FULL"` → **Restart & Run All**.
"""

CONFIG = """# ЕДИНСТВЕННАЯ ЯЧЕЙКА, КОТОРУЮ МОЖНО ИЗМЕНЯТЬ
MODE = "FULL"  # "FULL" или "SMOKE"
print("Режим:", MODE)
"""

ENV = """import importlib.util, subprocess, sys
if importlib.util.find_spec("lightgbm") is None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "lightgbm>=4.4,<5"])
for name in ("numpy", "polars", "sklearn", "lightgbm"):
    print(f"{name:10s}", getattr(__import__(name), "__version__", "?"))
"""

SELF = """SELF_TESTS = {**run_self_tests(), **run_v2_self_tests()}
for name, ok in SELF_TESTS.items():
    print("OK  " if ok else "FAIL", name)
assert all(SELF_TESTS.values()), "Самопроверки не пройдены"
"""

RUN = """CONFIG = make_config_v2(MODE)
RESULT = run_episode_v2(CONFIG)
print()
print("Статус:", RESULT["status"])
if RESULT.get("stop_reason"):
    print("Причина остановки:", RESULT["stop_reason"])
if RESULT.get("target_audit"):
    print("Доля v1-positives, начавшихся в D+1:", RESULT["target_audit"]["share_of_v1_positives_started_on_dplus1"])
if RESULT.get("selection"):
    print("Выбрано:", RESULT["selection"]["selected"], "—", RESULT["selection"]["reason"])
"""

SUMMARY = """import os
from pathlib import Path
from IPython.display import Markdown, display
OUT = Path(os.environ.get("LDT_OUTPUT_DIR", CONFIG["output_dir"]))
display(Markdown((OUT / "summary_failure_onset_v2_ru.md").read_text(encoding="utf-8")))
for name in ("results_failure_onset_v2.json", "summary_failure_onset_v2_ru.md"):
    path = OUT / name
    print("-", name, "существует:" , path.exists())
"""


def build_notebook() -> dict:
    audit_runtime = (HERE / "pre2025_audit_runtime.py").read_text(encoding="utf-8")
    v2_runtime = (HERE / "episode_v2_runtime.py").read_text(encoding="utf-8")
    return {
        "cells": [
            markdown_cell(INTRO), markdown_cell(HOW), code_cell(CONFIG), code_cell(ENV),
            markdown_cell("## Runtime ноутбука 05 (фолды, метрики, эпизоды, бутстрэп, модели)\n"),
            code_cell(audit_runtime),
            markdown_cell("## Runtime эксперимента 13 (цель v2, cadence, отбор)\n"),
            code_cell(v2_runtime),
            markdown_cell("## Самопроверки\n"),
            code_cell(SELF),
            markdown_cell("## Прогон\n"),
            code_cell(RUN),
            markdown_cell("## Сводка\n"),
            code_cell(SUMMARY),
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3"},
            "kaggle": {"accelerator": "none"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_notebook(), ensure_ascii=False, indent=1), encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
