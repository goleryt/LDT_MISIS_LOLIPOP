"""Generate the standalone CPU Kaggle notebook 05 (pre-2025 baseline/leakage/propensity audit)."""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / "notebooks" / "kaggle" / "05_lightgbm_propensity_research_cpu.ipynb"


def embeddable(source: str) -> str:
    """Убирает резервный импорт соседних модулей: в notebook их имена уже определены ячейками выше."""
    start = source.index("try:\n    from pre2025_audit_runtime import")
    end = source.index("except ImportError:", start)
    end = source.index("\n", source.index("pass", end)) + 1
    return source[:start] + "# (импорты соседних модулей не нужны: они выполнены ячейками выше)\n" + source[end:]


def markdown_cell(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(True)}


def code_cell(source: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
            "source": source.splitlines(True)}


INTRO = """# 05 · LightGBM: аудит baseline, shortcut-признаков и channel propensity (CPU)

**Вычисления:** CPU, в Kaggle выбрать **Accelerator = None**.

Исследование на обезличенной panel v2 (`panel_manifest_v2.json`), **только данные до 2025 года**:

1. **Baseline-лестница** B0–B4 и воспроизведение текущего LightGBM (M0, `safe_recurrence`, 21 признак).
2. **Аудит shortcut-признаков**: без recurrence, без календаря, без каталога, только condition-признаки.
3. **Clean-history sensitivity** `k ∈ {0, 7, 14, 30}` — отдельно native и common cohort.
4. **Channel propensity** (вторичный эксперимент) — identity-like историческая характеристика канала, не причинный признак.
5. **Unseen/support-проверки**: новые каналы, новые объекты, неподдержанные типы датчиков.
6. **Парные 95% CI** (500 повторов бутстрэпа блоками календарных недель, `seed=42`) и **gates** выбора кандидата.
7. **Раздел 9 — погода (05W)**: суточная погода Москвы (Open-Meteo, ERA5, CC BY 4.0) как признаки, плацебо-проверка
   на сезонный shortcut и верхняя оценка пользы метеопрогноза. План: `docs/EXPERIMENT_05W_WEATHER_RU.md`.

Цель `target_failure_state_onset_24h` — наблюдаемый proxy: состояние `Неисправен`/`Обесточен` в сутки D+2
по признакам до конца D. **Это не подтверждённая физическая поломка** и не строгий onset
(состояние могло начаться в D+1).

| фолд | train | calibration / порог | validation |
|---|---|---|---|
| fold_2023 | 2019–2020, 2022 | 2023 H1 | 2023 H2 |
| fold_2024 | 2019–2020, 2022–2023 | 2024 H1 | 2024 H2 |

2021 — один раз как stress-срез после выбора. 2025 H2 и 2026 **не загружаются**: строки после 2024 года участвуют
только в агрегатных проверках контракта. Для propensity H1 делится по времени: первая половина — подбор `m`,
вторая — Platt и порог.

Результаты в `/kaggle/working`: `research_results_pre2025.json`, `research_summary_ru.md` (разделы 1–8) и
`results_weather_pre2025.json`, `summary_weather_ru.md` (раздел 9). Погода встроена в notebook (SHA-256 проверяется),
интернет на Kaggle не нужен.
Только агрегаты: ни ключей каналов/объектов, ни построчных прогнозов.
"""

HOW = """## Как запустить

1. **Add Input** → приватный dataset с `panel_manifest_v2.json` (путь не нужен — manifest ищется автоматически).
2. **Settings → Accelerator → None.**
3. Сначала можно `MODE = "SMOKE"` (≈1/20 каналов, 30 деревьев, 50 повторов бутстрэпа) — результаты `non_comparable`.
4. Для настоящего прогона `MODE = "FULL"`, затем **Restart & Run All**.
5. Основной прогон (≈9 мин) и раздел погоды (≈4–6 мин) включаются флагами `RUN_MAIN` и `RUN_WEATHER`:
   если основной прогон уже сделан, можно поставить `RUN_MAIN = False` и получить только погоду.
"""

CONFIG = """# ЕДИНСТВЕННАЯ ЯЧЕЙКА, КОТОРУЮ МОЖНО ИЗМЕНЯТЬ
MODE = "FULL"  # "FULL" или "SMOKE"; SMOKE-результаты помечаются non_comparable
RUN_MAIN = True     # разделы 1–8: baseline, ablations, clean-history, propensity (≈9 мин FULL)
RUN_WEATHER = True  # раздел 9: погода (≈4–6 мин FULL)
print("Режим:", MODE, "| основной прогон:", RUN_MAIN, "| погода:", RUN_WEATHER)
"""

ENV = """# Проверка среды: CPU, версии библиотек. LightGBM ставится, только если его нет в образе.
import importlib.util, subprocess, sys
if importlib.util.find_spec("lightgbm") is None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "lightgbm>=4.4,<5"])
for name in ("numpy", "pandas", "polars", "sklearn", "lightgbm"):
    print(f"{name:10s}", getattr(__import__(name), "__version__", "?"))
try:
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                         capture_output=True, text=True, timeout=20).stdout.strip()
except Exception:
    gpu = ""
print("GPU:", gpu or "нет (Accelerator = None) — как и требуется")
"""

SELF = """SELF_TESTS = run_self_tests()
for name, ok in SELF_TESTS.items():
    print("OK  " if ok else "FAIL", name)
assert all(SELF_TESTS.values()), "Самопроверки не пройдены"
"""

RUN = """CONFIG = make_config(MODE)
RESULT = run_research(CONFIG) if RUN_MAIN else {"status": "skipped (RUN_MAIN = False)"}
print()
print("Статус:", RESULT["status"])
if RESULT.get("stop_reason"):
    print("Причина остановки:", RESULT["stop_reason"])
if "selection" in RESULT:
    print("Текущий кандидат:", RESULT["selection"]["selected"], "—", RESULT["selection"]["reason"])
"""

SUMMARY = """import os
from pathlib import Path
from IPython.display import Markdown, display
OUT = Path(os.environ.get("LDT_OUTPUT_DIR", CONFIG["output_dir"]))
if RUN_MAIN:
    display(Markdown((OUT / "research_summary_ru.md").read_text(encoding="utf-8")))
else:
    print("Основной прогон пропущен (RUN_MAIN = False).")
"""

MONTHLY = """import pandas as pd
if RUN_MAIN and RESULT.get("folds"):
    rows = []
    for fold_name, fold in RESULT["folds"].items():
        for model in ("B2_recurrence", "B3_rule", "B4_logistic", "M0_lightgbm", RESULT["selection"]["selected"]):
            for month in fold["models"][model].get("monthly", []):
                rows.append({"фолд": fold_name, "модель": model, "месяц": month["month"],
                             "PR-AUC": month["pr_auc"], "precision@50": month["precision_at_50_per_day"]})
    table = pd.DataFrame(rows).drop_duplicates()
    display(table.pivot_table(index=["фолд", "месяц"], columns="модель", values="PR-AUC").round(4))
    display(table.pivot_table(index=["фолд", "месяц"], columns="модель", values="precision@50").round(4))
else:
    print("Нет результатов по фолдам (прогон остановлен).")
"""

WEATHER_SELF = """WEATHER_SELF_TESTS = run_weather_self_tests()
for name, ok in WEATHER_SELF_TESTS.items():
    print("OK  " if ok else "FAIL", name)
assert all(WEATHER_SELF_TESTS.values()), "Самопроверки погоды не пройдены"
"""

WEATHER_RUN = """if RUN_WEATHER:
    WEATHER_CONFIG = make_config_weather(MODE)
    WEATHER_RESULT = run_weather(WEATHER_CONFIG)
    print("Статус:", WEATHER_RESULT["status"])
    if WEATHER_RESULT.get("stop_reason"):
        print("Причина остановки:", WEATHER_RESULT["stop_reason"])
    if "selection" in WEATHER_RESULT:
        print("Выбрано:", WEATHER_RESULT["selection"]["selected"], "—", WEATHER_RESULT["selection"]["reason"])
    display(Markdown((OUT / "summary_weather_ru.md").read_text(encoding="utf-8")))
else:
    print("Раздел погоды пропущен (RUN_WEATHER = False).")
"""

WEATHER_INTRO = """## 9. Погода Москвы как признак (эксперимент 05W)

План зафиксирован до обучения: `docs/EXPERIMENT_05W_WEATHER_RU.md`. Те же фолды, семплирование и параметры LightGBM,
что у M0, поэтому M0 здесь должен совпасть с разделом 1 (проверяется).

| модель | что добавлено | зачем |
|---|---|---|
| W1 | погода суток D и окна 3/7 суток до D | развёртываемый кандидат |
| P1 | та же погода, но на 364 суток позже (тот же день недели и сезон) | плацебо: погода это или сезон |
| W2 | W1 + фактическая погода D+1…D+2 | «идеальный прогноз» — только верхняя оценка |
| NC / W3 / P3 | без календаря; + погода; + плацебо | может ли погода заменить календарный shortcut |

Погода — Open-Meteo Historical Weather API (реанализ ERA5), одна точка на Москву, лицензия CC BY 4.0
(«Weather data by Open-Meteo.com»). Признак одинаков для всех каналов в сутки.
"""

FINISH = """print("Файлы для передачи команде:")
for name in ("research_results_pre2025.json", "research_summary_ru.md", "results_weather_pre2025.json", "summary_weather_ru.md"):
    path = OUT / name
    print("-", name, f"({path.stat().st_size / 1024:.0f} КБ)" if path.exists() else "— НЕ СОЗДАН")
print("Построчные прогнозы и идентификаторы не сохраняются.")
"""


def build_notebook() -> dict:
    runtime = (HERE / "pre2025_audit_runtime.py").read_text(encoding="utf-8")
    weather_data = (HERE / "weather_data.py").read_text(encoding="utf-8")
    weather_runtime = embeddable((HERE / "weather_runtime.py").read_text(encoding="utf-8"))
    return {
        "cells": [
            markdown_cell(INTRO), markdown_cell(HOW), code_cell(CONFIG), code_cell(ENV),
            markdown_cell("## Встроенный проверенный runtime\n\nКод встроен в notebook; репозиторий на Kaggle не нужен.\n"),
            code_cell(runtime),
            markdown_cell("## Самопроверки на синтетических данных\n"),
            code_cell(SELF),
            markdown_cell("## Основной прогон\n"),
            code_cell(RUN),
            markdown_cell("## Сводка для команды\n"),
            code_cell(SUMMARY),
            markdown_cell("## Помесячная динамика (validation)\n"),
            code_cell(MONTHLY),
            markdown_cell(WEATHER_INTRO),
            markdown_cell("### Встроенные данные погоды (gzip+base64, SHA-256 проверяется)\n"),
            code_cell(weather_data),
            markdown_cell("### Встроенный runtime раздела 9\n"),
            code_cell(weather_runtime),
            code_cell(WEATHER_SELF),
            code_cell(WEATHER_RUN),
            code_cell(FINISH),
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
