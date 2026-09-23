"""Generate four standalone, Russian-language Kaggle notebooks."""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / "notebooks" / "kaggle"


SPECS = [
    {
        "file": "01_rule_cpu_for_colleague.ipynb",
        "model": "rule",
        "title": "Rule baseline: базовые правила",
        "recipient": "для коллеги",
        "hardware": "CPU; в Kaggle выбрать Accelerator = None",
        "iterations": 0,
        "explanation": (
            "Правило не обучается. Оно берёт максимум из текущей доли тревог, "
            "половины предыдущей доли тревог и индикатора наблюдаемого неисправного состояния. "
            "Это минимальная точка сравнения: сложная модель должна давать заметно лучший результат."
        ),
    },
    {
        "file": "02_lightgbm_cpu_for_colleague.ipynb",
        "model": "lightgbm",
        "title": "LightGBM: градиентный бустинг",
        "recipient": "для коллеги",
        "hardware": "CPU; в Kaggle выбрать Accelerator = None",
        "iterations": 500,
        "explanation": (
            "LightGBM последовательно добавляет деревья, каждое из которых исправляет ошибки предыдущих. "
            "Он хорошо ловит нелинейные связи в табличных признаках. CPU-вариант выбран для надёжности: "
            "он не требует сборки OpenCL/CUDA-версии библиотеки."
        ),
    },
    {
        "file": "03_logistic_cpu_for_mi.ipynb",
        "model": "logistic",
        "title": "Logistic regression: интерпретируемая модель",
        "recipient": "для Mi",
        "hardware": "CPU; в Kaggle выбрать Accelerator = None",
        "iterations": 0,
        "explanation": (
            "Логистическая регрессия считает линейную комбинацию признаков, а затем превращает её в вероятность "
            "p=1/(1+exp(-z)). Числовые признаки заполняются медианой и масштабируются, категории кодируются one-hot. "
            "Модель важна как понятный обучаемый бейзлайн."
        ),
    },
    {
        "file": "04_catboost_gpu_for_mi.ipynb",
        "model": "catboost",
        "title": "CatBoost: бустинг с категориями",
        "recipient": "для Mi",
        "hardware": "NVIDIA GPU; в Kaggle выбрать Accelerator = GPU",
        "iterations": 500,
        "explanation": (
            "CatBoost строит ансамбль деревьев и нативно обрабатывает `тип_инж_системы` и `тип_датчика`. "
            "GPU ускоряет обучение, но суммирование чисел на GPU не детерминировано побитово, поэтому малые различия между повторами нормальны."
        ),
    },
]


def markdown_cell(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(True)}


def code_cell(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(True),
    }


def notebook(spec: dict, runtime_source: str) -> dict:
    model = spec["model"]
    config = f'''# ЕДИНСТВЕННАЯ ЯЧЕЙКА, КОТОРУЮ МОЖНО ИЗМЕНЯТЬ
CONFIG = {{
    "run_mode": "full",  # "full" или "smoke"; smoke нельзя сравнивать
    "target": "target_failure_state_onset_24h",
    "feature_variant": "safe_recurrence",
    "negative_to_positive_ratio": 20,
    "minimum_precision": 0.20,
    "alert_budget_per_day": 50,
    "cooldown_hours": 72,
    "random_seed": 20260919,
    "iterations": {spec['iterations']},
    "catboost_task_type": "GPU",
}}
MODEL_NAME = "{model}"
OUTPUT_DIR = "/kaggle/working"
print("Модель:", MODEL_NAME, "| режим:", CONFIG["run_mode"])
'''
    install = f'''# Проверка среды. Установка нужна только если пакета нет в образе Kaggle.
import importlib.util, subprocess, sys
required = {{"lightgbm": "lightgbm>=4.4,<5", "catboost": "catboost>=1.2,<2"}}
if MODEL_NAME in required and importlib.util.find_spec(MODEL_NAME) is None:
    print("Пакет не найден; устанавливаем", required[MODEL_NAME])
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", required[MODEL_NAME]])
if MODEL_NAME == "catboost":
    subprocess.run(["nvidia-smi"], check=True)
print("Среда готова.")
'''
    run = '''panel, manifest, manifest_path = load_panel()
print("Пакет проверен:", manifest_path.parent)
print("Строк:", panel.height, "| даты:", manifest["date_min"], "—", manifest["date_max"])
print("Сырые идентификаторы отсутствуют:", not manifest["raw_identifiers_included"])

result = run_model(panel, manifest, MODEL_NAME, CONFIG, OUTPUT_DIR)
m = result["metrics_2025_h2"]
print()
print("ИТОГ 2025 H2")
print("PR-AUC:", round(m["pr_auc"], 4))
print("Precision:", round(m["precision"], 4))
print("Recall:", round(m["recall"], 4))
print("Ложных тревог / 1000 канал-дней:", round(m["false_alerts_per_1000_eligible_channel_days"], 2))
print(result["warning_ru"])
'''
    finish = '''save_validation_charts(MODEL_NAME, OUTPUT_DIR)
from pathlib import Path
print()
print("Файлы для передачи команде:")
for path in sorted(Path(OUTPUT_DIR).glob(f"*{MODEL_NAME}*")):
    print("-", path.name)
'''
    intro = f'''# {spec['title']}

**Кому:** {spec['recipient']}  
**Вычисления:** {spec['hardware']}

## Что прогнозируем

Строка описывает канал датчика на конец дня **D**. День **D+1** даёт не менее 24 часов на реакцию. Цель равна 1, если в день **D+2** наблюдается переход в прокси-состояние `Неисправен` или `Обесточен`.

**Это не подтверждённый физический отказ.** Это наблюдаемый прокси из журнала событий.

## Зачем нужна эта модель

{spec['explanation']}

## Что делать

1. Прикрепите приватный dataset с `panel_manifest_v2.json` через **Add Input**.
2. Выберите указанный выше Accelerator.
3. Нажмите **Run All**. Путь к dataset вводить не нужно.
4. Передайте `results_{model}.json` и PNG-график команде.

Перед полным запуском можно поставить `run_mode="smoke"`, но его метрики нельзя сравнивать.
'''
    return {
        "cells": [
            markdown_cell(intro),
            code_cell(config),
            code_cell(install),
            markdown_cell("## Общий проверенный код\n\nЯчейка ниже встроена в notebook, поэтому репозиторий на Kaggle не нужен.\n"),
            code_cell(runtime_source),
            code_cell(run),
            code_cell(finish),
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3"},
            "kaggle": {"accelerator": "gpu" if model == "catboost" else "none"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    runtime_source = (HERE / "kaggle_runtime.py").read_text(encoding="utf-8")
    for spec in SPECS:
        payload = notebook(spec, runtime_source)
        (OUTPUT / spec["file"]).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(OUTPUT / spec["file"])


if __name__ == "__main__":
    main()
