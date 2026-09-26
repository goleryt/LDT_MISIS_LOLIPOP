"""Generate the standalone CPU Kaggle notebook 15 (models on event-panel v3 targets + typed-score contract)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / "notebooks" / "kaggle" / "15_targets_v3_models_cpu.ipynb"


def _cell_id(kind: str, source: str) -> str:
    return hashlib.sha1((kind + source).encode("utf-8")).hexdigest()[:8]


def markdown_cell(source: str) -> dict:
    return {"cell_type": "markdown", "id": _cell_id("m", source), "metadata": {}, "source": source.splitlines(True)}


def code_cell(source: str) -> dict:
    return {"cell_type": "code", "id": _cell_id("c", source), "execution_count": None, "metadata": {}, "outputs": [],
            "source": source.splitlines(True)}


INTRO = """# 15 · Модели на целях панели v3 и typed scores для бэкенда (CPU)

**Вычисления:** CPU, **Accelerator = None**, интернет не нужен.

Вход — выход ноутбука 14 (`event_panel_v3/` с `panel_manifest_v3.json`; SHA-256 частей проверяется).
План зафиксирован до обучения: `docs/EXPERIMENT_15_TARGETS_V3_RU.md`.

Для каждой цели ТЗ отдельно (T2a потеря связи, T2b длительная потеря связи, T2c обесточивание и длительное,
T1a технические значения, T4 газ ≥ 1 %):

| модель | что это | зачем |
|---|---|---|
| P0 | частота цели по типу датчика | нижняя граница |
| R1 | правило: недавние эпизоды того же вида | «канал мигал недавно» |
| L1 | логистическая регрессия | простая модель |
| G1 | LightGBM на всех признаках | основной кандидат |
| G2 | G1 без календаря | проверка shortcut (день недели в 05 давал половину gain) |
| G3 | G1 без типа датчика/системы | проверка identity-shortcut |

Фолды как в 05: `fold_2023` (train до 2023, калибровка 2023 H1, валидация 2023 H2) и `fold_2024`.
2021 (переход системы мониторинга, FAQ) и январь 2022 исключены; 2025+ не загружается.
Purging по `d_label_decision_end`. Метрики: PR-AUC, ROC-AUC, Brier/ECE после Platt, бюджет top-k в сутки
(5/10/25/50) с cooldown 72 ч и без, парный блочный бутстрэп по неделям.

**Выход** (`/kaggle/working`): `results_targets_v3.json`, `summary_targets_v3_ru.md`,
`backend_typed_scores_v3.json` (typed-score контракт: `incident_type`, `score_kind`, `evidence_level`, покрытие,
причины abstain). Только агрегаты — ни ключей каналов, ни построчных прогнозов.
"""

HOW = """## Как запустить

1. **Add Input** → выход ноутбука 14 (Notebook Output) — `panel_manifest_v3.json` ищется автоматически.
2. **Settings → Accelerator → None.**
3. `MODE = "SMOKE"` — ≈1/10 каналов, 60 деревьев, 20 повторов бутстрэпа (несколько минут), результаты `non_comparable`.
4. `MODE = "FULL"` → **Save Version → Save & Run All**. Можно считать не все цели: список `TARGETS`.
"""

CONFIG = """# ЕДИНСТВЕННАЯ ЯЧЕЙКА, КОТОРУЮ МОЖНО ИЗМЕНЯТЬ
MODE = "FULL"   # "FULL" или "SMOKE"
TARGETS = [
    "target_t2a_link_onset", "target_t2b_link_sustained",
    "target_t2c_power_onset", "target_t2c_power_sustained",
    "target_t1a_tech_value", "target_t4_gas_cross",
]
print("Режим:", MODE, "| целей:", len(TARGETS))
"""

ENV = """import os, platform, warnings
warnings.filterwarnings("ignore", category=UserWarning)
import numpy, polars, sklearn, lightgbm
for m in (numpy, polars, sklearn, lightgbm):
    print(f"{m.__name__:10s}", m.__version__)
print("CPU       ", os.cpu_count())
"""

SELF = """import tempfile
SELF_TESTS = run_targets_self_tests(Path(tempfile.mkdtemp()))
for name, ok in SELF_TESTS.items():
    print("OK  " if ok else "FAIL", name)
assert all(SELF_TESTS.values()), "Самопроверки не пройдены"
"""

RUN = """from pathlib import Path
CONFIG = make_config_targets(MODE, {"targets": TARGETS})
RESULT = run_targets_v3(CONFIG)
print()
print("Статус:", RESULT["status"], "| время:", RESULT["runtime_s"], "с")
for t, level in RESULT["decisions"].items():
    print(f"  {t:30s} {level}")
"""

SUMMARY = """from IPython.display import Markdown, display
OUT = Path(CONFIG["output_dir"])
display(Markdown((OUT / "summary_targets_v3_ru.md").read_text(encoding="utf-8")))
"""

BUDGET = """import json
import pandas as pd
res = json.loads((OUT / "results_targets_v3.json").read_text(encoding="utf-8"))
rows = []
for t, r in res["targets"].items():
    f = r["folds"].get("fold_2024", {})
    for m, x in f.get("models", {}).items():
        for k, b in x["budget"].items():
            rows.append({"цель": t.replace("target_", ""), "модель": m, "k/сутки": int(k),
                         "precision": b["precision"], "recall": b["recall"],
                         "precision (cooldown)": b["precision_cooldown"], "recall (cooldown)": b["recall_cooldown"]})
if rows:
    table = pd.DataFrame(rows)
    display(table.pivot_table(index=["цель", "k/сутки"], columns="модель", values="precision (cooldown)").round(3))
    display(table.pivot_table(index=["цель", "k/сутки"], columns="модель", values="recall (cooldown)").round(3))
"""

COVERAGE = """cov = res["coverage"]
print("Строк pre-2025 без 2021:", f"{cov['rows_pre2025_without_2021']:,}")
display(pd.DataFrame({t.replace("target_", ""): c["reasons"] for t, c in cov["targets"].items()}).fillna(0).astype(int))
"""

FINISH = """print("Файлы для передачи команде и бэкенду:")
for name in ("results_targets_v3.json", "summary_targets_v3_ru.md", "backend_typed_scores_v3.json"):
    p = OUT / name
    print("-", name, f"({p.stat().st_size / 1024:.0f} КБ)" if p.exists() else "— НЕ СОЗДАН")
print("Построчные прогнозы и идентификаторы не сохраняются.")
"""


def build_notebook() -> dict:
    runtime = (HERE / "target_models_v3_runtime.py").read_text(encoding="utf-8")
    return {
        "cells": [
            markdown_cell(INTRO), markdown_cell(HOW), code_cell(CONFIG), code_cell(ENV),
            markdown_cell("## Встроенный runtime\n\nКод встроен; репозиторий на Kaggle не нужен.\n"),
            code_cell(runtime),
            markdown_cell("## Самопроверки на синтетике\n"),
            code_cell(SELF),
            markdown_cell("## Прогон\n"),
            code_cell(RUN),
            markdown_cell("## Сводка для команды\n"),
            code_cell(SUMMARY),
            markdown_cell("## Бюджетные кривые (fold_2024, с cooldown 72 ч)\n\nprecision — доля верных среди выданных "
                          "k строк в сутки; recall — доля всех положительных строк валидации, пойманных бюджетом.\n"),
            code_cell(BUDGET),
            markdown_cell("## Покрытие: где цель определена, а где abstain\n"),
            code_cell(COVERAGE),
            code_cell(FINISH),
        ],
        "metadata": {
            "kaggle": {"accelerator": "none", "dataSources": [], "isInternetEnabled": False, "language": "python",
                       "sourceType": "notebook", "isGpuEnabled": False},
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_notebook(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("written", OUTPUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
