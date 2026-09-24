# Интерфейс экспериментальной ML-модели для backend

## 1. Ответы на вопросы

| Вопрос | Ответ |
|---|---|
| Формат модели | ZIP-пакет backend_experimental_model.zip. Внутри находятся experimental_cold_start_model.joblib, predictor.py, model_contract.json, пример входа и файл зависимостей. |
| Способ вызова | Backend загружает bundle один раз при старте процесса и вызывает batch-predictor в памяти. Нельзя загружать модель заново или запускать отдельный процесс для каждого запроса. |
| Вход | Один или несколько records с датой среза, причинной длиной истории и дневными агрегатами. Полный список приведён ниже. |
| Выход | Калиброванный score от 0 до 1, окно прогноза, ветка модели и технические статусы. Score — вероятность наблюдаемого proxy-состояния, а не подтверждённой аварии. |
| Предобработка | Дневная агрегация сырых событий выполняется backend/data-контуром. Преобразование готовых признаков, категории, пропуски, routing и калибровка находятся внутри ML-bundle. Top-K и cooldown выполняются backend после модели. |

## 2. Назначение

Модель работает только в статусе experimental_shadow. Она не должна
автоматически создавать инцидент, заявку или команду исполнительному устройству.

По данным до конца дня D модель оценивает вероятность того, что в интервале
[D+2, D+3) будет зарегистрировано proxy-состояние Неисправен или Обесточен.

Это не вероятность физической поломки и не диагноз причины. Текущая метка также
не является строго доказанным onset: состояние могло начаться в день D+1.

2026 и 2025 H2 не используются для обучения или выбора этой версии.

## 3. Архитектурная граница

    Источник событий
        → причинная дневная агрегация до конца D
        → внутренний ML endpoint
        → score для каждого канала
        → общий top-K и cooldown
        → shadow-результат

Это внутренний API. Если основной backend написан не на Python, модель следует
запустить в небольшом Python ML-sidecar. Joblib не следует читать из JavaScript,
Java, Go или другого несовместимого runtime.

Идентификатор канала нужен backend для сопоставления ответа, но не является
признаком модели. ML-слой не должен логировать сырой ид_канала_данных,
ид_объект или исходные записи журнала.

## 4. Методы

### POST /internal/ml/v1/failure-state-proxy/predict

Основной batch-метод. Один record также передаётся массивом из одного элемента.

Метод должен:

- принять готовые дневные признаки;
- проверить схему и дату среза;
- вызвать загруженный predictor;
- вернуть результаты в порядке входных items.

Рекомендуемый batch: от 1 до 5 000 элементов. Запрос отклоняется целиком, если
хотя бы один элемент не прошёл проверку. Partial success в первой версии не
использовать.

### GET /internal/ml/v1/failure-state-proxy/model-info

Возвращает model_version, feature_contract_version, target_code,
selected_policy, SHA-256 bundle, время загрузки, статус experimental_shadow и
версии runtime. Не возвращает train-данные, категории или статистики признаков.

### GET /internal/ml/v1/failure-state-proxy/health/live

Проверяет только работу процесса.

### GET /internal/ml/v1/failure-state-proxy/health/ready

Ready=true только если bundle загружен, SHA-256 совпал, зависимости совместимы,
встроенный smoke-прогноз выполнен и backend поддерживает feature-контракт.

## 5. Envelope запроса

| Поле | Тип | Обязательное | Назначение |
|---|---|---:|---|
| request_id | string/UUID | да | Идемпотентность и трассировка. |
| feature_contract_version | string | да | Для этой версии: daily-panel-v2+cold-start-v1. |
| items | array of objects | да | От 1 до 5 000 элементов. |
| items[].entity_ref | string | да | Внутренняя ссылка backend на канал; не передаётся модели. |
| items[].features | object | да | Поля модели. |

## 6. Поля features

Все ключи обязательны. Nullable-поля могут иметь значение null. Backend не
должен самостоятельно заменять null на 0.

### Служебные и eligibility

| Поле | Тип и ограничения | Значение |
|---|---|---|
| as_of_date | string YYYY-MM-DD | День D, на конец которого рассчитаны признаки. |
| d_observed_days_so_far | integer, не меньше 1 | Число наблюдаемых channel-days до D включительно. |
| d_current_failure_state | boolean | Последнее состояние на D является proxy failure-state. При true возвращается score=null. |

### Текущий день D

| Поле | Тип и ограничения | Значение |
|---|---|---|
| d_event_count_24h | integer, не меньше 1 | Число событий канала. |
| d_alarm_count_24h | integer, от 0 до d_event_count_24h | Число тревожных событий. |
| d_alarm_share_24h | number от 0 до 1 | Доля тревожных событий. |
| d_failure_state_event_count_24h | integer, не меньше 0 | Число записей Неисправен или Обесточен. |
| d_value_numeric_mean_24h | nullable number | Среднее распознанных числовых значений. |
| d_value_numeric_min_24h | nullable number | Минимальное числовое значение. |
| d_value_numeric_max_24h | nullable number | Максимальное числовое значение. |
| d_value_numeric_std_24h | nullable number, не меньше 0 | Стандартное отклонение. |
| d_value_numeric_last | nullable number | Последнее числовое значение по времени доступности. |
| d_state_n_unique_24h | integer, не меньше 0 | Число различных текстовых состояний. |

### Причинная история

| Поле | Тип и ограничения | Значение |
|---|---|---|
| d_gap_days_since_previous | nullable integer, не меньше 1 | Дней от предыдущего наблюдаемого channel-day. |
| d_event_count_previous_24h | nullable integer, не меньше 1 | Число событий предыдущего наблюдаемого дня. |
| d_alarm_count_previous_24h | nullable integer, не меньше 0 | Число тревожных событий предыдущего дня. |
| d_alarm_share_previous_24h | nullable number от 0 до 1 | Доля тревог предыдущего дня. |
| d_value_numeric_previous | nullable number | Последнее числовое значение предыдущего дня. |
| d_days_since_failure_state_event | nullable integer, не меньше 0 | Дней с последней ранее зарегистрированной записи proxy failure-state. |

### Календарь и справочник

| Поле | Тип и ограничения | Значение |
|---|---|---|
| d_weekday | integer от 1 до 7 | День недели из as_of_date; 1 — понедельник. |
| d_month | integer от 1 до 12 | Месяц из as_of_date. |
| d_catalogue_match | boolean | Канал найден в справочнике. |
| тип_инж_системы | nullable string | Точное значение исходного поля. |
| тип_датчика | nullable string | Точное значение исходного поля. |

Правила проверки:

- разрешены только конечные числа; NaN, Infinity и строки вместо чисел запрещены;
- при наличии min и max должно выполняться
  d_value_numeric_min_24h <= d_value_numeric_max_24h;
- d_weekday и d_month должны совпадать с as_of_date;
- неизвестные категории разрешены и обрабатываются внутри bundle;
- target, будущие события, d_channel_key, d_object_key, ид_канала_данных и
  ид_объект запрещены внутри features.

## 7. Пример входа

    {
      "request_id": "7a093f5b-c7cd-46cf-a598-6f0e4c6e8483",
      "feature_contract_version": "daily-panel-v2+cold-start-v1",
      "items": [
        {
          "entity_ref": "backend-channel-7421",
          "features": {
            "as_of_date": "2026-09-21",
            "d_observed_days_so_far": 3,
            "d_current_failure_state": false,
            "d_event_count_24h": 12,
            "d_alarm_count_24h": 1,
            "d_alarm_share_24h": 0.083333,
            "d_failure_state_event_count_24h": 0,
            "d_value_numeric_mean_24h": 21.4,
            "d_value_numeric_min_24h": 20.8,
            "d_value_numeric_max_24h": 22.1,
            "d_value_numeric_std_24h": 0.42,
            "d_value_numeric_last": 21.8,
            "d_state_n_unique_24h": 1,
            "d_gap_days_since_previous": 1,
            "d_event_count_previous_24h": 11,
            "d_alarm_count_previous_24h": 0,
            "d_alarm_share_previous_24h": 0.0,
            "d_value_numeric_previous": 21.1,
            "d_days_since_failure_state_event": null,
            "d_weekday": 1,
            "d_month": 9,
            "d_catalogue_match": true,
            "тип_инж_системы": "Система мониторинга",
            "тип_датчика": "Датчик температуры"
          }
        }
      ]
    }

Entity_ref используется только для сопоставления и не включается в DataFrame,
который передаётся predictor.

## 8. Выход

Envelope успешного ответа:

| Поле | Тип | Значение |
|---|---|---|
| request_id | string/UUID | Повторяет входное значение. |
| model_version | string | Версия загруженного bundle. |
| feature_contract_version | string | Версия входной схемы. |
| decision_status | string | Для этой версии experimental_shadow. |
| predictions | array of objects | Результаты в порядке входных items. |

Один prediction:

| Поле | Тип | Значение |
|---|---|---|
| entity_ref | string | Ссылка соответствующего входа. |
| target_code | string | failure_state_presence_24_48h_proxy_v1. |
| as_of_date | string/date | День D. |
| window_start | string/date | Начало окна D+2. |
| window_end_exclusive | string/date | Исключающая граница D+3. |
| score | number от 0 до 1 или null | Калиброванная вероятность proxy; null для строки, не подлежащей прогнозу. |
| score_kind | string | calibrated_observable_state_proxy_probability. |
| route | enum | cold_start, mature_history или fallback base_lightgbm. |
| threshold | number от 0 до 1 | Порог из calibration-периода bundle. |
| is_alert_candidate | boolean | Прошёл ли локальный порог; это ещё не итоговый alert. |
| eligibility_status | enum | eligible или already_in_proxy_state. |
| model_version | string | Фактически использованная версия. |

Пример:

    {
      "request_id": "7a093f5b-c7cd-46cf-a598-6f0e4c6e8483",
      "model_version": "cold-start-router-proxy-v1",
      "feature_contract_version": "daily-panel-v2+cold-start-v1",
      "decision_status": "experimental_shadow",
      "predictions": [
        {
          "entity_ref": "backend-channel-7421",
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
          "model_version": "cold-start-router-proxy-v1"
        }
      ]
    }

Score=0.18 означает оценку около 18% для регистрации выбранного proxy-состояния
в окне [2026-09-23, 2026-09-24) при информации до конца 2026-09-21. Это нельзя
называть 18% вероятностью физической поломки или основанием автоматически создать
инцидент.

Threshold=0.21 приведён только как пример. Backend использует значение из
конкретного bundle и не хардкодит его.

## 9. Где выполняется предобработка

### Backend/data-контур до модели

Backend должен:

1. взять только события, доступные к концу as_of_date;
2. собрать текущие и предыдущие дневные агрегаты;
3. поддерживать причинные поля истории;
4. определить текущее proxy-состояние;
5. добавить справочные значения и d_catalogue_match;
6. передать поля с правильными типами.

Raw-event aggregation намеренно не находится внутри bundle. Нельзя сканировать
всю историю Parquet или журналов при каждом API-запросе. Признаки должны
поддерживаться в operational feature store или подготовленной дневной таблице.

### Внутри ML-bundle

Backend не должен повторно реализовывать:

- train-fitted category mapping;
- обработку неизвестных категорий;
- обработку nullable числовых значений;
- type-relative robust deviation;
- выбор cold-start или mature-history ветки;
- Platt calibration;
- fallback на базовый LightGBM.

Иначе offline и online predictions разойдутся.

### Backend после модели

Backend применяет:

- общий лимит top-50 в день;
- cooldown 72 часа по каналу;
- сопоставление entity_ref;
- shadow-логирование;
- бизнес-правила отображения.

## 10. Ошибки

| HTTP | Ситуация |
|---:|---|
| 400 | Некорректный JSON, пустой items или превышен размер batch. |
| 409 | Неподдерживаемая feature_contract_version. |
| 422 | Пропущено поле, неверный тип, диапазон или несогласованные агрегаты. |
| 503 | Модель не загружена, не прошла SHA-проверку или readiness smoke-test. |
| 500 | Неожиданная ошибка inference. |

Ошибка содержит error_code, краткое описание и request_id. Сырые признаки и
идентификаторы не включаются в текст ошибки и обычные application logs.

## 11. Что реализовать backend-команде

- внутренний batch endpoint и три служебных GET-метода;
- строгую проверку feature-контракта до inference;
- однократную загрузку и SHA-проверку bundle при старте;
- operational storage причинных дневных признаков;
- сопоставление entity_ref без передачи ID в модель;
- top-K/cooldown policy после score;
- версионирование model и feature contract;
- shadow-метрики: latency, route, eligibility, распределение score, число
  кандидатов и ошибки — без сырых records;
- атомарную замену bundle и быстрый rollback.

До выхода из shadow-режима отдельно утверждаются цель, порог, alert-budget,
качество на unseen-каналах и допустимая нагрузка ложных тревог.
