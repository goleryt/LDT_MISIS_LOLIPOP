# Как запустить четыре ML-notebook в Kaggle

## Что кому передать

| Файл | Кому | Accelerator |
|---|---|---|
| `01_rule_cpu_for_colleague.ipynb` | коллеге | `None` (CPU) |
| `02_lightgbm_cpu_for_colleague.ipynb` | коллеге | `None` (CPU) |
| `03_logistic_cpu_for_mi.ipynb` | Mi | `None` (CPU) |
| `04_catboost_gpu_for_mi.ipynb` | Mi | `GPU` |

LightGBM намеренно запускается на CPU. Это убирает ненадёжную сборку OpenCL/CUDA-версии LightGBM. CatBoost запускается только на NVIDIA GPU.

## 1. Создать приватный Dataset

1. Открыть Kaggle → **Datasets** → **New Dataset**.
2. Загрузить готовый `data/ldt_sensor_panel_v2_kaggle.zip` или всю папку `data/kaggle_private_panel_v2`.
3. Назвать dataset, например, `ldt-sensor-panel-v2`.
4. Оставить видимость **Private**. Не публиковать dataset.
5. Открыть **Settings → Sharing** и добавить Kaggle-аккаунт коллеги как `Can view`.

В dataset нет сырых журналов, `ид_канала_данных`, `ид_объект`, названий датчиков и строк 2026 года. Ключи `d_channel_key` и `d_object_key` необратимо псевдонимизированы.

## 2. Импортировать notebook

1. Kaggle → **Code** → **New Notebook** → **File → Import Notebook**.
2. Выбрать нужный `.ipynb`.
3. Справа нажать **Add Input**, найти приватный `ldt-sensor-panel-v2` и добавить его.
4. Не менять путь к файлу: notebook сам найдёт `panel_manifest_v2.json`.
5. Для CatBoost: **Settings → Accelerator → GPU**. Для остальных: **None**.
6. Нажать **Run All**.

Если LightGBM или CatBoost отсутствует в текущем образе Kaggle, первая ячейка сама установит пакет. В этом редком случае нужно временно включить **Internet** и повторить Run All.

Права на notebook и dataset раздельные. Если коллега не видит данные, нужно проверить именно **Dataset Settings → Sharing**, а не только Sharing у notebook.

## 3. Что можно менять

В каждом notebook есть одна ячейка `CONFIG`:

- `run_mode="smoke"` — быстрая проверка. Её метрики нельзя сравнивать.
- `run_mode="full"` — полный сравнимый запус.
- `feature_variant="safe_recurrence"` — основной вариант.
- `core`, `no_same_day_failure` — безопасные абляции.
- `with_object_key_ablation` — только диагностика запоминания объектов; не основная модель.

Для первого сравнения ничего менять не нужно.

## 4. Что вернуть команде

После запуска открыть раздел **Output** и скачать:

- `results_<model>.json` — главный сравнимый результат;
- `charts_<model>_2025_h2.png` — PR-кривая и калибровка;
- файл модели и калибратор, если они есть.

Не сравнивать результаты, если хотя бы в одном JSON стоит `SMOKE_NON_COMPARABLE`, другой `panel_data_sha256` или другой `feature_variant`.

## 5. Missing-target поток 07–12

Это отдельный поток. Его scores нельзя напрямую сравнивать с `target_failure_state_onset_24h`: цели разные.

1. Запустить `07_missing_targets_panel_audit_cpu.ipynb` с Accelerator = None: сначала smoke, потом full.
2. Из FULL output 07 создать новый private Dataset. Он должен содержать `missing_targets_manifest_v1.json` и три указанных в нём файла.
3. Прикрепить этот Dataset к 08–11. Все четыре notebook требуют GPU в FULL-режиме.
4. Скачать result/prediction/summary outputs 08–11 и прикрепить их к `12_missing_targets_scorecard_cpu.ipynb`.
5. Запустить 12 на CPU. Он не переобучает модели и не усредняет access/fire/flood/availability scores.

Нельзя публиковать Dataset. Права Dataset и Notebook по-прежнему настраиваются раздельно.
