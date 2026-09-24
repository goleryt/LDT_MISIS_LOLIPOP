"""Generate the Codex-owned standalone Kaggle notebooks 07, 10, 11 and 12.

Notebooks 08 and 09 are intentionally delegated to Claude and are therefore
not generated here; this prevents accidental overwrites during integration.
"""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / "notebooks" / "kaggle"


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


def _payload(cells: list[dict], accelerator: str) -> dict:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3"},
            "kaggle": {"accelerator": accelerator},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def _install(gpu: bool) -> str:
    requirement = '{"polars": "polars>=1.0,<2", "sklearn": "scikit-learn>=1.4,<2"}'
    device = """
import torch
if CONFIG["run_mode"] == "full":
    if not torch.cuda.is_available():
        raise RuntimeError("FULL-режим требует Kaggle NVIDIA GPU")
    print("GPU:", torch.cuda.get_device_name(0))
else:
    print("SMOKE: CPU-surrogate разрешён; метрики несравнимы.")
""" if gpu else 'print("Accelerator: None (CPU)")\n'
    return f'''# Проверка среды; пакеты ставятся только если их нет.
import importlib.util
import subprocess
import sys

requirements = {requirement}
missing = [spec for module, spec in requirements.items() if importlib.util.find_spec(module) is None]
if missing:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *missing])
{device}'''


def notebook_07(runtime: str) -> dict:
    intro = """# 07 — Аудит и сборка missing-target panel

**Вычисления:** CPU, Accelerator = None.

Ноутбук проверяет source panel v2 и создаёт две согласованные панели: object-day и channel-element.
Все новые цели — observable proxy. Они не являются подтверждёнными пожарами, затоплениями,
несанкционированным доступом или физической поломкой.

Прикрепите private Dataset с `panel_manifest_v2.json`, затем Run All. После FULL-запуска создайте из output новый private Kaggle Dataset для notebooks 08–11.
"""
    config = '''# ЕДИНСТВЕННАЯ ЯЧЕЙКА, КОТОРУЮ МОЖНО МЕНЯТЬ
CONFIG = {
    "run_mode": "full",  # "smoke" или "full"; smoke несравним
    "random_seed": 20260922,
}
OUTPUT_DIR = "/kaggle/working"
print("Режим:", CONFIG["run_mode"], "| CPU")
'''
    run = '''panel, source_manifest, source_manifest_path = load_source_panel()
print("Исходный пакет проверен:", source_manifest_path.parent)
print("Строк:", panel.height, "| SHA-256 совпала")
manifest = export_missing_target_bundle(panel, source_manifest, OUTPUT_DIR, CONFIG)
print("Создано object-day:", manifest["rows"]["object_day"])
print("Создано channel-element:", manifest["rows"]["channel_element"])
print("Цели — proxy, не confirmed incidents.")
'''
    finish = '''from pathlib import Path
print("\\nФайлы output для private Dataset:")
for path in sorted(Path(OUTPUT_DIR).glob("*")):
    if path.is_file():
        print("-", path.name)
'''
    return _payload(
        [
            markdown_cell(intro),
            code_cell(config),
            code_cell(_install(False)),
            markdown_cell("## Встроенный проверенный runtime\n"),
            code_cell(runtime),
            code_cell(run),
            code_cell(finish),
        ],
        "none",
    )


def notebook_10(runtime: str) -> dict:
    intro = """# 10 — Access, fire and flooding synthetic challenge

**Вычисления:** Kaggle CPU, Accelerator = None.

Подтверждённых инцидентов нет. Используются реальные трёхдневные контексты и отдельно
сгенерированные траектории для access, fire и flood. Семейство 2 не используется при обучении.
Оценка на реальных данных — только нагрузка тревог. Output E4 — `synthetic_scenario_match`,
не вероятность инцидента. Старый results_10 с бюджетом 50/сутки был насыщен и не годится для отбора.
"""
    config = '''# ЕДИНСТВЕННАЯ ЯЧЕЙКА, КОТОРУЮ МОЖНО МЕНЯТЬ
CONFIG = {
    "run_mode": "full",  # smoke несравним с полным прогоном
    "alert_budget_per_day": 5,
    "synthetic_count_per_family": 500,
    "random_seed": 20260922,
}
OUTPUT_DIR = "/kaggle/working"
print("Режим:", CONFIG["run_mode"], "| CPU")
'''
    run = '''object_day, channel, manifest, manifest_path = load_missing_target_bundle()
print("Пакет 07 проверен:", manifest_path.parent)
results = run_multitarget_synthetic_challenge(object_day, manifest, CONFIG, OUTPUT_DIR)
for target, result in results.items():
    print(target, "|", result["selection"]["status"])
print("Вероятности реальных инцидентов не выводятся.")
'''
    finish = '''from pathlib import Path
for path in sorted(Path(OUTPUT_DIR).glob("*synthetic_scenario*")):
    print(path.name, "| создан:", path.exists())
'''
    return _payload(
        [markdown_cell(intro), code_cell(config), code_cell(_install(False)), code_cell(runtime), code_cell(run), code_cell(finish)],
        "none",
    )


def notebook_11(runtime: str) -> dict:
    intro = """# 11 — Channel availability/dropout proxy

**Вычисления:** Kaggle NVIDIA GPU для FULL.

Когорта определяется в D: канал и хотя бы один peer наблюдаются сейчас. D+1 и позднее
используются только для proxy-разметки или цензурирования. Модель оценивается на всей
когорте D; отдельно показаны доля разрешённых меток и тревоги с неизвестным исходом.
Это не вероятность физической поломки.
"""
    config = '''# ЕДИНСТВЕННАЯ ЯЧЕЙКА, КОТОРУЮ МОЖНО МЕНЯТЬ
CONFIG = {
    "run_mode": "full",  # smoke: logistic surrogate вместо TCN, метрики несравнимы
    "negative_to_positive_ratio": 20,
    "minimum_precision": 0.20,
    "alert_budget_per_day": 50,
    "cooldown_hours": 72,
    "sequence_length": 14,
    "tcn_hidden": 48,
    "epochs": 10,
    "batch_size": 1024,
    "max_tcn_train_rows": 200000,
    "bootstrap_repeats": 200,
    "min_positives_for_pr_auc": 20,
    "minimum_label_coverage": 0.8,
    "maximum_unresolved_alert_share": 0.2,
    "random_seed": 20260922,
}
OUTPUT_DIR = "/kaggle/working"
print("Режим:", CONFIG["run_mode"], "| FULL = NVIDIA GPU")
'''
    run = '''object_day, channel, manifest, manifest_path = load_missing_target_bundle()
print("Пакет 07 проверен:", manifest_path.parent)
result = run_dropout_experiment(channel, manifest, CONFIG, OUTPUT_DIR)
print("Выбрано:", result["selection"]["selected_model"])
print("Статус:", result["selection"]["decision_status"])
print("Это availability proxy, не physical-failure probability.")
'''
    finish = '''from pathlib import Path
for path in sorted(Path(OUTPUT_DIR).glob("*dropout*")):
    print(path.name, "| создан:", path.exists())
'''
    return _payload(
        [markdown_cell(intro), code_cell(config), code_cell(_install(True)), code_cell(runtime), code_cell(run), code_cell(finish)],
        "gpu",
    )


def notebook_12(runtime: str) -> dict:
    intro = """# 12 — Cross-target scorecard

**Вычисления:** CPU, Accelerator = None. Модели не переобучаются.

Прикрепите outputs 08, 09 и новую версию 11 как private Kaggle inputs. Новая версия 10
добавляет E4 сценарные оценки; при её отсутствии они отмечаются `not_evaluated`.
Ноутбук проверит typed-score contract и соберёт scorecard.
Access, fire, flooding и availability не усредняются в одну «магическую» вероятность.
"""
    config = '''# ЕДИНСТВЕННАЯ ЯЧЕЙКА, КОТОРУЮ МОЖНО МЕНЯТЬ
CONFIG = {
    "run_mode": "full",
}
OUTPUT_DIR = "/kaggle/working"
print("Режим:", CONFIG["run_mode"], "| CPU | без retraining")
'''
    intro += "\nBackend-gate переносится из результатов 08/09/10/11: при запрете `score = null`, `decision_status = abstain`; `research_score` хранится только для анализа.\n"
    run = '''scorecard = build_missing_targets_scorecard(None, OUTPUT_DIR, CONFIG)
print("Модулей:", len(scorecard["modules"]))
print("Строк typed scores:", scorecard["score_rows"])
print("Усреднение между целями:", scorecard["cross_target_averaging"])
'''
    finish = '''from pathlib import Path
for name in ["missing_targets_scorecard.json", "missing_targets_scores.parquet", "missing_targets_scorecard_ru.md", "missing_targets_router_contract.json"]:
    path = Path(OUTPUT_DIR) / name
    print(name, "| создан:", path.exists())
'''
    return _payload(
        [markdown_cell(intro), code_cell(config), code_cell(_install(False)), code_cell(runtime), code_cell(run), code_cell(finish)],
        "none",
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    runtime = (HERE / "missing_targets_runtime.py").read_text(encoding="utf-8")
    notebooks = {
        "07_missing_targets_panel_audit_cpu.ipynb": notebook_07(runtime),
        "10_flood_synthetic_anomaly_gpu.ipynb": notebook_10(runtime),
        "11_channel_dropout_sequence_gpu.ipynb": notebook_11(runtime),
        "12_missing_targets_scorecard_cpu.ipynb": notebook_12(runtime),
    }
    for name, payload in notebooks.items():
        path = OUTPUT / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
