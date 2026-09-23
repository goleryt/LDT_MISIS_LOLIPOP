# Задача Claude: Kaggle notebooks 08 и 09

Нужно создать два независимых Kaggle notebook:

1. `08_access_deepsets_gpu.ipynb`;
2. `09_fire_transfer_deepsets_gpu.ipynb`.

Оба ноутбука получают одинаковый private Kaggle Dataset — output notebook 07. Схема 07 не меняется Claude. Если поля нет, нужно остановиться с ясной ошибкой, а не изобретать fallback.

## Входной контракт 07

Автопоиск под `/kaggle/input`, без username/slug:

- `missing_targets_manifest_v1.json`;
- `missing_target_registry_v1.json`;
- `object_day_panel_v1.parquet`;
- `object_channel_day_panel_v1.parquet`.

Проверить:

- `schema_version == "missing-targets-1.1"`;
- SHA-256 каждого файла;
- row counts, date range, absence 2026 и сырых `ид_канала_данных`/`ид_объект`;
- наличие exact target/date columns.

Ключи `d_channel_key` и `d_object_key` можно использовать только для grouping/evaluation, но не как model features. Их нельзя печатать.

## Общий temporal contract

- Features: только до конца D.
- D+1: lead time.
- Outcome: D+2, одни сутки.
- Fold 1: train target windows до 2023-01-01; calibration 2023 H1; validation 2023 H2.
- Fold 2: train target windows до 2024-01-01; calibration 2024 H1; validation 2024 H2.
- 2021 не входит в train. Если используется, только как retrospective migration slice, не forward test.
- 2025 H2 и 2026 не используются для выбора.
- Validation не прореживается. Train negatives можно проредить 20:1 с inverse-probability weights.
- Category levels, scalers, imputers, calibration и thresholds не видят validation.
- Calendar features (`d_month`, `d_weekday`) по умолчанию не используются.

## Notebook 08 — access

Цель: `target_access_corroboration_24_48h_proxy`.

Точный смысл: в D+2 на объекте наблюдались тревожные сигналы не менее чем от двух разных access-типов. Это не факт несанкционированного доступа.

Сравнить на одних validation-строках:

- A0 global prevalence;
- A1 train-fitted prevalence по sensor-composition signature, global fallback;
- A2 deterministic multi-signal rule;
- A3 regularized logistic regression;
- A4 Deep Sets на наборе channel elements объекта.

Deep Sets: channel-level numeric vector + train-fitted embedding `тип_датчика`, shared `phi`, masked mean+max pooling, `rho` binary head. Unknown type = reserved index. Padding mask не участвует в pooling.

Обязательно:

- recurrence baseline и clean-history slice: `d_days_since_access_corroboration >= 30` или null;
- seen/unseen object определяются train+calibration; пустой unseen slice = `not_evaluable`;
- output score называется `calibrated_corroboration_proxy_probability`.

## Notebook 09 — fire

Цель: `target_fire_corroboration_24_48h_proxy`.

Точный смысл: в D+2 на объекте наблюдались тревожные сигналы не менее чем от двух разных fire-типов. Это не подтверждённый пожар.

Сравнить:

- F0 prevalence;
- F1 fixed smoke/fire recurrence rule;
- F2 regularized logistic regression;
- F3 тот же Deep Sets со scratch;
- F4 та же архитектура: pretrain на `target_any_alarm_observed_Dplus2_proxy`, затем fine-tune на fire proxy;
- F5 direct differentiable AP surrogate только если в validation каждого фолда >= 20 positives.

Если в фолде < 20 positives:

- PR-AUC и её CI не печатаются как надёжные;
- гипотеза получает `not_evaluable`;
- backend candidate не выбирается;
- сохраняются только counts и aggregate sensitivity.

Обязателен clean-history slice: `d_days_since_fire_corroboration >= 30` или null.

## Метрики и отбор

Для каждой модели:

- PR-AUC и lift над prevalence;
- Brier score, ECE;
- top-50 object alerts/day;
- episode precision/recall при cooldown 72h;
- false alerts / 1000 eligible object-days;
- clean-history и seen/unseen object slices;
- paired confidence intervals блоками дат.

Отбор симметричный: neural model не выбирается, если episode precision хуже лучшего простого baseline более чем на 1 п.п., растут false alerts, либо paired CI по primary metric включает zero. При ничьей выбирается простая модель.

## Режимы и outputs

Каждый notebook:

- русский markdown, ошибки, charts и summary;
- одна ячейка `CONFIG`;
- `run_mode = smoke/full`; smoke явно `non_comparable`;
- Kaggle NVIDIA GPU preflight и запись фактического device;
- не печатает raw rows/ключи;
- не выдаёт weak label за confirmed incident.

Outputs 08:

- `results_access_missing_target.json`;
- `predictions_access_missing_target.parquet`;
- `summary_access_missing_target_ru.md`;
- selected model artifact, если отбор вообще возможен.

Outputs 09:

- `results_fire_missing_target.json`;
- `predictions_fire_missing_target.parquet`;
- `summary_fire_missing_target_ru.md`;
- selected model artifact только при достаточной support.

В prediction parquet разрешены только pseudonymous key, dates, target, selected score, fold, `score_kind`, `evidence_level`. Он не должен содержать feature values.

## Что вернуть

Один ZIP:

- два `.ipynb`;
- шесть result/prediction/summary outputs из FULL-запусков;
- `REPRODUCE_08_09.md`;
- SHA-256 всех файлов.

Перед FULL запустить smoke. Если MPS/CUDA/GPU не доступен в FULL, остановиться; не подменять полный прогон CPU-суррогатом.

