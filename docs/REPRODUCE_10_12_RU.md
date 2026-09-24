# Финальный цикл Kaggle: сценарии, доступность, scorecard

## Что уже установлено

`results_10.zip` от прежнего ноутбука 10 **не является успешным flood-детектором**: лимит 50 тревог/сутки охватывал почти все объекты, на реальном фоне получено около 1000 тревог на 1000 объект-дней. Synthetic sensitivity = 1 в этих условиях тривиальна. `results_11_v2.zip` относится к старому контракту `dropout-selection-2.0`: его validation-когорта определялась с использованием будущих наблюдений. Оба архива сохраняются для аудита, но не являются входом нового итогового решения.

## Порядок запуска

1. Загрузить локальный `notebooks/kaggle/10_flood_synthetic_anomaly_gpu.ipynb` как новую версию Kaggle notebook 10. **Несмотря на историческое имя файла, новая версия работает на CPU: Accelerator = None.** Прикрепить приватный Dataset с выходом ноутбука 07. Запустить `Restart & Run All` в `full`. Сохранить все `results_*_synthetic_scenario.json`, `predictions_*_synthetic_scenario.parquet`, `model_*_synthetic_selected.joblib`, `model_*_synthetic_contract.json` и русские summary. Исходный `results_10.zip` не подменять новыми файлами.
2. Загрузить локальный `notebooks/kaggle/11_channel_dropout_sequence_gpu.ipynb` как новую версию ноутбука 11. Включить NVIDIA GPU, прикрепить тот же Dataset 07 и выполнить `full`. Проверить в JSON `selection_contract_version = dropout-selection-3.0`, `asof_validation_rows`, `label_coverage`, `unresolved_alert_share` и `backend_candidate`. Сохранить весь output, включая модель и контракт. Старый `results_11_v2.zip` не использовать для scorecard.
3. Загрузить `notebooks/kaggle/12_missing_targets_scorecard_cpu.ipynb`, Accelerator = None. Прикрепить приватные outputs 08, 09, **нового** 11 и, если готов, **нового** 10. Старый 10 имеет другие имена результатов и будет отмечен `not_evaluated`; старый 11 будет отвергнут по версии контракта. Запустить `Restart & Run All` и сохранить `missing_targets_scorecard.json`, `missing_targets_scores.parquet`, `missing_targets_router_contract.json`, `missing_targets_scorecard_ru.md`.

Scorecard версии `missing-target-router-3.0` переносит флаги `backend_candidate` (08/09/11) и `backend_scenario_score_allowed` (10). Если флаг `false` или отсутствует, модуль получает `decision_status = abstain` и `score_exposure_allowed = false`; в строках `score = null`. Исходное число остаётся в `research_score` только для анализа. Это относится к flooding из `results_10_v2.zip` и availability из `results_11_v2_last.zip`: их нельзя маршрутизировать как backend-предсказания. E4 с разрешённым показом — только совпадение с синтетическим сценарием, не вероятность инцидента.

## Значение результатов

- E1 `channel_availability_proxy_probability`: вероятность наблюдаемого proxy временной потери канала, **не** физического отказа. PR-AUC считается только на строках с разрешённой proxy-меткой. Операционная нагрузка и нижняя оценка episode precision считаются на всей когорте, известной в D; доля цензурированных исходов выводится отдельно.
- E2 `calibrated_corroboration_proxy_probability`: доступ/пожар — будущая корроборация сигналов, **не** подтверждённый инцидент. Для пожара имеющейся поддержки недостаточно для выбора модели.
- E4 `synthetic_scenario_match`: access/fire/flood — совпадение с искусственно заданным сценарием. Обучение использует семейства 0–1; семейство 2 остаётся контрольным. `heldout_family_recall_at_budget` измеряет только synthetic challenge. `real_background_alerts_per_1000` — нагрузка на исторических строках, **не** доказанная частота ложных инцидентных тревог. Реальный incident PR-AUC не существует.
- Скоры разных целей нельзя усреднять, сравнивать по PR-AUC друг с другом или подписывать как вероятность пожара/затопления/проникновения.

## Контракт для backend

В `ml/sensor_failure/missing_targets_runtime.py` доступны `predict_dropout_bundle(history, frame, bundle_dir)` и `predict_scenario_bundle(history, frame, bundle_dir, task)`. Они читают сохранённые модель и JSON-контракт, проверяют SHA-256, строят ту же историю признаков и возвращают типизированные строки с `score`, `score_kind`, `evidence_level`, окном и `decision_status`. `history` — канонические, обезличенные channel-day или object-day признаки **до** момента D; это не API сырых событий. Для dropout нужна история всех peer-каналов объекта, для synthetic — минимум три календарных дня объектной истории. Backend отдельно применяет top-K/cooldown, хранит версию модели и показывает evidence level. При `abstain` `score = null`. Порог из контракта не следует трактовать как подтверждённое решение об инциденте.

Физическую локацию из псевдонимов восстановить нельзя. До появления отдельной таблицы связей интерфейс должен показывать только доступный псевдоним/группу либо воздерживаться от карты. LightGBM failure-state остаётся отдельным исследовательским кандидатом: его старые результаты не добавляются как подтверждённая вероятность отказа и не усредняются с данным scorecard.
