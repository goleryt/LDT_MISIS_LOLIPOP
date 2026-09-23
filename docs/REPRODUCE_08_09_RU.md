# Как воспроизвести notebooks 08 (access) и 09 (fire)

## Что нужно

- Kaggle Notebook, **Settings → Accelerator → GPU** (NVIDIA T4 или P100).
- Private Kaggle Dataset с **FULL-выходом notebook 07**: `missing_targets_manifest_v1.json`,
  `missing_target_registry_v1.json`, `object_day_panel_v1.parquet`, `object_channel_day_panel_v1.parquet`.
- **Smoke-бандл 07 не подходит.** Smoke-режим 07 оставляет только последние ~120 дней, в нём нет фолдов
  2023/2024. Поэтому и smoke-, и full-прогоны 08/09 запускаются на FULL-бандле 07. На smoke-бандле ноутбук
  остановится с `status: contract_failed` и объяснением причины.
- Интернет не нужен: polars, scikit-learn и torch есть в стандартном GPU-образе Kaggle.
- В notebook 09 решение обучать F5 принимается только по числу положительных примеров
  в train и первой половине calibration H1; validation не определяет набор обучаемых моделей.
- H1 разделён хронологически: первая половина нужна для ранней остановки Deep Sets,
  вторая — для Platt-калибровки и выбора порога.

## Шаги (для каждого notebook отдельно)

1. Создайте новый пустой Kaggle Notebook и выберите **File → Import Notebook**:
   `08_access_deepsets_gpu.ipynb` или `09_fire_transfer_deepsets_gpu.ipynb`.
   Создавайте отдельный Kaggle Notebook для каждого файла.
2. **Add Input** → private Dataset с выходом 07. Подключить ровно один такой dataset: манифест ищется
   автоматически, два одинаковых манифеста — ошибка.
3. **Accelerator → GPU.**
4. В ячейке `CONFIG` поставить `"run_mode": "smoke"` → **Run All**. Проверить, что статус `completed`
   и самопроверки `OK`.
5. Поставить `"run_mode": "full"` → **Restart & Run All**.

Если вы экономите GPU-квоту, можно сразу запустить FULL: встроенные самопроверки
выполняются до обучения. При любой ошибке пришлите текст первой упавшей ячейки.

Если в FULL не найден GPU, ноутбук останавливается со статусом `gpu_required_not_available`
и ничего не обучает. Подмены на CPU нет.

## Режимы

| режим | что урезано | время (оценка) | RAM |
| --- | --- | --- | --- |
| smoke | ~1/3 объектов, 3 эпохи, 2 эпохи pretrain, 50 повторов бутстрэпа | 1–3 мин | 2–4 ГБ |
| full | ничего: 30 эпох (ранняя остановка по H1), 10 эпох pretrain, 500 повторов бутстрэпа | 08: 5–15 мин, 09: 10–30 мин | 4–8 ГБ |

Оценки времени экстраполированы с синтетической фикстуры (24 объекта: access FULL ≈ 1,5 мин, fire FULL ≈ 1,5 мин
на CPU). На реальной панели объектов около 78, на GPU обучение Deep Sets быстрее, чем на CPU.
Smoke-результаты помечены `non_comparable_smoke`, сравнивать их нельзя.

## Что проверяется до обучения

- `schema_version == "missing-targets-1.1"`, SHA-256 трёх файлов, число строк — функцией загрузки из 07;
- дополнительно: `run_mode` бандла `full`, `date_min`/`date_max`, отсутствие 2026 года и сырых
  `ид_канала_данных`/`ид_объект`, наличие всех нужных полей цели и дат;
- всё с окном цели после 2025-01-01 отбрасывается сразу после проверки, 2025 H2 и 2026 не используются;
- самопроверки на синтетике: эпизоды совпадают с `episode_metrics` из 07, PR-AUC совпадает со sklearn,
  Deep Sets инвариантен к перестановке и паддингу, Smooth-AP дифференцируем.

## Выходы (`/kaggle/working`)

| 08 | 09 |
| --- | --- |
| `results_access_missing_target.json` | `results_fire_missing_target.json` |
| `predictions_access_missing_target.parquet` | `predictions_fire_missing_target.parquet` |
| `summary_access_missing_target_ru.md` | `summary_fire_missing_target_ru.md` |
| `model_access_selected.*` и `model_access_selected_calibration.json` — если выбран backend-кандидат | `model_fire_selected.*` и `model_fire_selected_calibration.json` — если выбран backend-кандидат |

В predictions девять колонок: `d_object_key` (псевдонимный), `d_cutoff_date`, `d_target_start_date`,
`d_target_end_date_exclusive`, цель, `selected_score`, `fold`, `score_kind`, `evidence_level`.
Значений признаков там нет. Формат совместим с проверками scorecard в notebook 12.

## Статусы отбора (`selection.decision_status`)

| статус | смысл |
| --- | --- |
| `selected_proxy_model` | поддержка достаточна, основная метрика различает модели; модель выбрана по gates |
| `not_evaluable_insufficient_positives` | в validation какого-то фолда < 20 positives; backend-кандидата нет |
| `not_evaluable_primary_budget_saturated` | бюджет 50 объектов/сутки покрывает ≥ 90% активных объектов, episode recall не различает модели; backend-кандидата нет. Смотрите `selection.sensitivity_budget` (бюджет 5) |

## Что вернуть команде

1. Шесть выходов FULL (results, predictions, summary для 08 и 09), а также файлы модели
   и калибровки, если они созданы.
2. Статус из вывода каждого ноутбука.
3. Файл `SHA256SUMS.txt`, пересчитанный по этим выходам:
   `sha256sum results_* predictions_* summary_* > SHA256SUMS.txt`.

Для notebook 12 обязательно приложить полный FULL-выход каждого ноутбука, включая
JSON и Parquet. Выходы 08/09 являются результатами двух development-фолдов до 2025 года:
сравнивать PR-AUC между access, fire и availability как одну шкалу качества нельзя.
Перед выпуском итоговой модели потребуется отдельная проверка 2025 H2 без выбора
архитектуры по этому периоду и упаковка полного online-препроцессинга.
