"""Generate the standalone CPU Kaggle notebook for the cold-start model."""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / "notebooks" / "kaggle" / "06_cold_start_router_cpu_for_mi.ipynb"


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


def build_notebook() -> dict:
    base_runtime = (HERE / "kaggle_runtime.py").read_text(encoding="utf-8")
    cold_runtime = (HERE / "cold_start_runtime.py").read_text(encoding="utf-8")
    intro = """# Cold-start router: экспериментальная модель для новых каналов

**Вычисления:** CPU, в Kaggle выбрать Accelerator = None.

Ноутбук не использует 2025 H2 или 2026 для выбора и обучения. Он:

1. сравнивает обычный LightGBM с парой специализированных моделей;
2. направляет первые семь наблюдаемых дней канала в cold-start модель;
3. использует только причинно доступную длину истории;
4. добавляет train-fitted отклонение от типичных значений своего тип_датчика;
5. оставляет обычный LightGBM, если router не проходит pre-2025 gates;
6. создаёт ZIP для backend в экспериментальном shadow-режиме.

Цель остаётся техническим proxy: наличие Неисправен или Обесточен в день D+2
по данным до конца D. Это не подтверждённая физическая поломка и пока не строгий
onset: состояние могло начаться в промежуточный день D+1.
"""
    config = """# ЕДИНСТВЕННАЯ ЯЧЕЙКА, КОТОРУЮ МОЖНО ИЗМЕНЯТЬ
CONFIG = {
    "run_mode": "full",  # сначала "smoke", затем "full"
    "cold_days": 7,
    "negative_to_positive_ratio": 20,
    "minimum_precision": 0.20,
    "alert_budget_per_day": 50,
    "cooldown_hours": 72,
    "iterations": 500,
    "bootstrap_repeats": 500,
    "robust_stats_max_rows": 200_000,
    "random_seed": 20260921,
}
OUTPUT_DIR = "/kaggle/working"
print("Режим:", CONFIG["run_mode"], "| CPU | cold days:", CONFIG["cold_days"])
"""
    install = """# Проверка среды. Интернет Kaggle нужен только если LightGBM отсутствует.
import importlib.util
import subprocess
import sys

if importlib.util.find_spec("lightgbm") is None:
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "-q", "lightgbm>=4.4,<5"
    ])
print("Среда готова; GPU не используется.")
"""
    run = """panel, manifest, manifest_path = load_panel()
print("Проверен пакет:", manifest_path.parent)
print("Строк:", panel.height, "| даты:", manifest["date_min"], "—", manifest["date_max"])
print("2026 отсутствует:", not manifest["contains_2026_rows"])

result = run_cold_start_research(panel, manifest, CONFIG, OUTPUT_DIR)
print()
print("Выбранная политика:", result["selection"]["selected_policy"])
for reason in result["selection"]["reasons"]:
    print("-", reason)
print("Использован 2025 H2:", result["uses_2025_h2_for_selection_or_training"])
print("ZIP для backend:", result["backend_bundle"]["bundle_zip"])
print("SHA-256:", result["backend_bundle"]["bundle_sha256"])
"""
    finish = """from pathlib import Path
print()
print("Скачайте после FULL-запуска:")
for name in [
    "backend_experimental_model.zip",
    "results_cold_start_router.json",
]:
    path = Path(OUTPUT_DIR) / name
    print("-", path, "| существует:", path.exists())
print()
print("Smoke нужен только для проверки кода; его модель и метрики передавать нельзя.")
"""
    return {
        "cells": [
            markdown_cell(intro),
            code_cell(config),
            code_cell(install),
            markdown_cell(
                "## Проверенный общий runtime\n\n"
                "Код встроен в notebook; подключать репозиторий к Kaggle не нужно.\n"
            ),
            code_cell(base_runtime),
            markdown_cell("## Cold-start обучение, оценка и backend export\n"),
            code_cell(cold_runtime),
            code_cell(run),
            code_cell(finish),
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3"},
            "kaggle": {"accelerator": "none"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(build_notebook(), ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
