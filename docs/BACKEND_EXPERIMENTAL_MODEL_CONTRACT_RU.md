# Контракт экспериментальной ML-модели для backend

## Статус

Модель предназначена для временного **shadow-режима** и интеграционной проверки.
Она не является финальной production-моделью и не должна автоматически создавать
инцидент или заявку.

Модель оценивает вероятность наблюдаемого proxy-состояния «Неисправен» или
«Обесточен» в окне [D+2, D+3) по данным, доступным до конца дня D. Это не
вероятность подтверждённой физической поломки. Текущая метка также не доказывает
строгий onset: состояние могло начаться в промежуточный день D+1.

## Что запустить в Kaggle

Ноутбук: notebooks/kaggle/06_cold_start_router_cpu_for_mi.ipynb.

- Accelerator: None (CPU).
- Сначала выполнить run_mode="smoke" только для проверки.
- Затем выполнить чистый Restart and Run All с run_mode="full".
- Скачать:
  - backend_experimental_model.zip;
  - results_cold_start_router.json.

В ZIP находятся модель, runtime, зависимости, JSON-контракт и пример входа.
Ноутбук сам выберет cold-start router только если тот прошёл pre-2025 gates.
Иначе в ZIP будет активирован обычный LightGBM.

## Формат и вызов

Формат: Python joblib bundle с LightGBM-моделями и отдельный predictor.py.

    from predictor import load_bundle, predict

    bundle = load_bundle("experimental_cold_start_model.joblib")
    result = predict([record], bundle)

Зависимости перечислены в backend_model_requirements.txt.

## Предобработка

Внутри bundle:

- сопоставление категорий и обработка неизвестных значений;
- обработка пропусков LightGBM;
- отклонение показателей от train-fitted профиля своего тип_датчика;
- выбор cold-start или mature-history ветки;
- Platt-калибровка;
- порог экспериментального alert-кандидата.

Backend/data-контур обязан:

- собрать дневные агрегаты только из событий, доступных к концу D;
- причинно вести d_observed_days_so_far, включая текущий наблюдаемый день;
- не подставлять будущие события и не считать отсутствие channel-day отрицательной
  меткой;
- применять общий top-K и cooldown после получения score.

Сырые ид_канала_данных, ид_объект, Kaggle-ключи и target на вход модели не
передаются.

## Вход

Каждый record содержит:

- as_of_date: строка YYYY-MM-DD;
- d_observed_days_so_far: целое число >=1;
- d_current_failure_state: boolean; true делает строку неeligible и возвращает
  score=null;
- тип_датчика, тип_инж_системы: nullable string;
- дневные числовые поля из model_contract.json: nullable number.

Точный список генерируется вместе с конкретным обученным bundle. Это исключает
расхождение между документацией и моделью.

## Выход

    {
      "request_index": 0,
      "target_code": "failure_state_presence_24_48h_proxy_v1",
      "as_of_date": "2026-09-21",
      "window_start": "2026-09-23",
      "window_end_exclusive": "2026-09-24",
      "score": 0.18,
      "score_kind": "calibrated_observable_state_proxy_probability",
      "route": "cold_start",
      "threshold": 0.21,
      "is_alert_candidate": false,
      "eligibility_status": "eligible",
      "decision_status": "experimental_shadow",
      "model_version": "cold-start-router-proxy-v1"
    }

score=0.18 означает оценённую вероятность proxy-состояния в указанном окне
среди сопоставимых наблюдаемых channel-days. Это число нельзя называть
вероятностью реальной аварии. is_alert_candidate — только результат порога;
окончательный список ограничивается top-K/cooldown снаружи модели.

## Правило для новых каналов

Первые семь наблюдаемых дней направляются в cold-start модель без recurrence-
признаков. После этого применяется mature-history модель. Если router не показал
статистически подтверждённого улучшения на unseen-каналах без ухудшения нагрузки,
bundle автоматически использует базовый LightGBM для всех строк.
