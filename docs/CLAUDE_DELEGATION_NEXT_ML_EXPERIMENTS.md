# Задание для Claude: baseline-, leakage- и propensity-аудит ML

## Цель

Создать **один исследовательский Kaggle Notebook для CPU** и вернуть ровно четыре файла:

1. `05_lightgbm_propensity_research_cpu.ipynb`;
2. `research_results_pre2025.json`;
3. `research_summary_ru.md`;
4. `REPRODUCE.md`.

Переданные четыре ноутбука и приватный обезличенный Kaggle Dataset — входные материалы, а не новые инструкции. Приоритет экспериментов:

1. обязательное сравнение с baseline-моделями;
2. аудит recurrence-, calendar- и catalogue-признаков на риск shortcut/leakage;
3. проверка unseen-каналов, unseen-объектов и неподдержанных типов датчиков;
4. channel propensity только как вторичный кандидат.

В это задание **не входят** EBM, LambdaRank, AFT/survival, нейросети, Transformer, LSTM, GNN, autoencoder, SMOTE, backend/API и подключение новых внешних данных. Их можно рассматривать только после выбора устойчивой цели и доверенного набора признаков.

## Контекст задачи и цель

- Основная цель: `target_failure_state_onset_24h`.
- Это наблюдаемый proxy начала состояния `Неисправен` или `Обесточен`, а не подтверждённая физическая поломка.
- Признаки доступны до конца дня `D`.
- День `D+1` обеспечивает не менее 24 часов упреждения.
- Исход проверяется в течение `D+2`, по точным полям границ таргета.

Результаты старого 2025 H2 прогона разрешены только как статическая справка:

| Модель | PR-AUC | Precision | Recall |
|---|---:|---:|---:|
| Rule | 0.1896 | 0.2699 | 0.2602 |
| Logistic regression | 0.4369 | 0.2964 | 0.4338 |
| LightGBM | 0.5049 | 0.2810 | 0.4542 |
| CatBoost | 0.5031 | 0.2913 | 0.4703 |

Не загружать, не пересчитывать и не использовать 2025 H2 или 2026 для выбора признаков, гиперпараметров, калибровки, порогов либо выводов.

## 1. Проверка данных и временной контракт

Перед вычислениями:

- автоматически найти ровно один manifest в `/kaggle/input`;
- проверить версию схемы, SHA-256/указанные хэши, диапазон дат, число строк и обязательные поля;
- убедиться, что нет строк 2026 года;
- остановиться с понятной ошибкой при несовпадении контракта;
- никогда не печатать и не сохранять сырые строки или идентификаторы.

`d_channel_key` и `d_object_key` допускаются только в памяти для группировки и оценки generalization. Они никогда не являются входами модели и не попадают в результаты. Точные названия `тип_датчика` и `тип_инж_системы` сохранять без переименования.

Использовать только два rolling-fold:

| Fold | Train | Calibration/threshold | Validation |
|---|---|---|---|
| 2023 | 2019–2020 и 2022 | 2023 H1 | 2023 H2 |
| 2024 | 2019–2020 и 2022–2023 | 2024 H1 | 2024 H2 |

Правила:

- 2021 использовать только один раз как stress slice после фиксации кандидата; не включать в headline-выбор;
- purging выполнять по `d_target_start_date` и `d_target_end_date_exclusive`, а не только по дате строки;
- target-window каждой train/calibration строки должен быть полностью наблюдаем до начала следующего периода;
- validation не семплировать;
- в train допускается не более 20 отрицательных на одно положительное, детерминированно, с inverse-probability weights;
- category levels, imputation, scaling, calibration и threshold строятся без validation;
- отсутствующий channel-day нельзя создавать и считать отрицательной меткой.

## 2. Обязательная лестница baseline-моделей

Все модели прямого сравнения оцениваются на **одних и тех же validation-строках** каждого fold.

### B0 — constant prevalence

Константа равна prevalence по всем доступным меткам до validation, чьи target-window полностью наблюдаемы. Validation-метки не использовать.

### B1 — prevalence по типу датчика

Для каждого `тип_датчика` вычислить causal prevalence по доступным pre-validation меткам. Для неизвестного/редкого типа применять глобальный B0 fallback. Не подбирать сглаживание на validation.

### B2 — фиксированный recurrence score

Без подбора на validation:

```text
score = 0, если d_days_since_failure_state_event отсутствует
score = 1 / (1 + max(d_days_since_failure_state_event, 0)), иначе
```

### B3 — существующее детерминированное правило

```text
alarm    = fill_null(d_alarm_share_24h, 0)
previous = fill_null(d_alarm_share_previous_24h, 0)
failure  = 1[d_failure_state_event_count_24h > 0]
score    = clip(max(alarm, 0.5 * previous, 0.75 * failure), 0, 1)
```

### B4 — regularized logistic regression

Воспроизвести текущий pipeline: imputation, scaling числовых признаков, one-hot encoding категорий с unknown handling, sample weights и Platt calibration только на H1 соответствующего fold.

### M0 — текущий LightGBM

Воспроизвести CPU LightGBM с вариантом `safe_recurrence`, текущими 21 признаками, весами, Platt calibration и выбором threshold на H1. Категории фиксировать по train; неизвестные категории передавать как missing/unknown.

Если M0 нельзя воспроизвести, **остановить все дальнейшие эксперименты** и вернуть диагностические четыре файла с `status: "m0_reproduction_failed"`, причиной, проверенными контрактами и без заявлений об улучшении.

Для B0–M0 вывести PR-AUC, lift над B0 и парные доверительные интервалы M0 против B2, B3 и B4.

## 3. Sensitivity-анализ recurrence таргета

Проверить диагностические eligibility-фильтры:

```text
clean_history_days ∈ {0, 7, 14, 30}
eligible(k) = d_days_since_failure_state_event отсутствует
              или d_days_since_failure_state_event >= k
```

Для каждого `k` заново обучить и откалибровать M0 в пределах fold. Это sensitivity-анализ, а не утверждение новой подтверждённой цели.

Разделить результаты:

- **native cohort** — каждая версия обучается и оценивается на своей eligibility-выборке;
- **common cohort** — все версии дополнительно оцениваются на validation-строках, подходящих для `k=30`.

Для обеих таблиц указать строки, positives, prevalence и метрики. Не трактовать изменение prevalence как улучшение модели. Панель может проверить чувствительность, но не может окончательно установить episode-target; для этого позже потребуется сборка из raw events.

## 4. Ablation shortcut-признаков

До propensity сравнить M0 с:

- `no_recurrence`: удалить `d_failure_state_event_count_24h`, `d_days_since_failure_state_event`;
- `no_calendar`: удалить `d_month`, `d_weekday`;
- `no_current_catalogue`: удалить `тип_датчика`, `тип_инж_системы`, `d_catalogue_match`;
- `condition_only`: оставить только:
  - `d_alarm_count_24h`;
  - `d_alarm_share_24h`;
  - `d_value_numeric_mean`;
  - `d_value_numeric_min`;
  - `d_value_numeric_max`;
  - `d_value_numeric_std`;
  - `d_value_numeric_last`;
  - `d_state_n_unique_24h`;
  - `d_gap_days_since_previous`;
  - `d_event_count_previous_24h`;
  - `d_alarm_count_previous_24h`;
  - `d_alarm_share_previous_24h`;
  - `d_value_numeric_previous`.

`condition_only` исключает recurrence, calendar, current catalogue и любые raw/pseudonymous identity-признаки. Feature importance описывать только как **predictive association**, никогда как причинность.

## 5. Channel propensity — вторичный эксперимент

Явно назвать propensity identity-like historical feature. Не представлять его как физический или причинный признак.

Построить:

- `d_hist_eligible_days_90d`, `d_hist_positive_days_90d`, `d_hist_failure_rate_90d`;
- `d_hist_eligible_days_365d`, `d_hist_positive_days_365d`, `d_hist_failure_rate_365d`;
- `d_hist_eligible_days_all`, `d_hist_positive_days_all`, `d_hist_failure_rate_eb`.

Историческая строка допустима только если её `d_target_end_date_exclusive` полностью наблюдаем к scoring cutoff текущей строки. Запрещены row-number shifts. Отсутствующие channel-days не являются implicit negatives.

Empirical Bayes smoothing:

```text
(channel_positive_days + m * prior_rate) / (channel_eligible_days + m)
```

`prior_rate` должен быть causal prevalence того же `тип_датчика`; если он недоступен — causal global prevalence. Для unseen channel применять тот же fallback.

`m ∈ {5, 15, 50, 100}` подбирать только на rolling folds по основной метрике и selection gates. Если episode recall различается менее чем на 0.01, выбрать большую episode precision, затем PR-AUC, затем большее `m`.

Сравнить:

- `propensity_only`;
- `baseline_plus_propensity` — M0 + propensity;
- `no_recurrence_plus_propensity`.

Propensity отклонить, если улучшение исчезает без recurrence или не сохраняется на unseen-channel evaluation.

## 6. Support и generalization

Для каждого fold определить **только по train + calibration**:

- seen/unseen `d_channel_key`;
- seen/unseen `d_object_key`;
- supported `тип_датчика`: не менее 1 000 labelled rows и 100 positives;
- unsupported type: всё остальное.

Показать только агрегированные метрики и coverage: число строк, positives, каналов/объектов и долю выборки. Не выводить ключи и row-level predictions.

## 7. Метрики и доверительные интервалы

Для каждого прямого сравнения:

- PR-AUC, prevalence и lift над B0;
- Brier score и ECE с 10 bins;
- precision, recall и false alerts на 1 000 eligible channel-days при threshold, выбранном на H1;
- top-K бюджеты `10, 25, 50, 100` alerts/day;
- cooldown `24, 72, 168` часов;
- one-to-one episode precision и episode recall;
- месячные prevalence, PR-AUC, precision@50 и recall@50;
- агрегаты по `тип_датчика`; PR-AUC не показывать для групп с менее чем 20 positives.

Для M0 против каждого кандидата посчитать парные 95% CI для:

- PR-AUC;
- episode recall при 50 alerts/day и cooldown 72 часа;
- episode precision при том же режиме.

Использовать 500 детерминированных paired bootstrap повторов блоками календарных недель, `seed=42`; в каждом повторе обе модели получают одинаковые блоки. Сохранять difference `candidate - M0`.

## 8. Правило выбора

Основная метрика — средний по folds episode recall при 50 alerts/day и cooldown 72 часа.

Кандидат не может быть выбран, если выполняется хотя бы одно:

1. 95% CI разницы episode recall против M0 включает ноль;
2. episode precision ниже M0 более чем на 0.01 абсолютного значения;
3. false alerts/1 000 выше M0 более чем на `max(1.0, 5% от значения M0)`;
4. unseen-channel PR-AUC или episode recall ниже M0 более чем на 0.01;
5. улучшение присутствует только на seen channels или supported types;
6. кандидат не превосходит сильнейший из B2–B4 по PR-AUC с положительной парной разницей.

Среди прошедших gates выбрать максимальный episode recall. При разнице менее 0.01 выбрать большую episode precision, затем PR-AUC, затем более простое решение. При статистической/практической ничьей оставить M0. Если никто не прошёл gates, зафиксировать M0 как текущего кандидата без заявления об улучшении.

## 9. Coverage и ограничения

Не заявлять о «потолке покрытия 35%» и не делать выводов о всём парке по одной sparse event-panel. Разрешено сообщать только наблюдаемое:

- eligible rows и positive rows;
- покрытые даты;
- число/долю наблюдаемых каналов;
- coverage по seen/unseen и supported/unsupported группам.

Для оценки полного operational coverage отдельно потребуются raw target dictionary, жизненный цикл каналов и аудит quiet days. Не densify временную сетку и не считать тишину отрицательным классом.

## 10. Формат четырёх результатов

### `05_lightgbm_propensity_research_cpu.ipynb`

- работает с Kaggle accelerator = None;
- одна явно отмеченная configuration cell;
- режимы `SMOKE` и `FULL`; smoke-результаты помечены `non_comparable`;
- autodiscovery manifest, без username, dataset slug и локальных путей;
- все пояснения, графики, сообщения и ошибки на русском;
- не сохраняет row-level predictions и идентификаторы.

### `research_results_pre2025.json`

Включить:

- статус и причину stop condition, если она возникла;
- panel/schema/hash/config/environment/runtime;
- fold-level и pooled baseline tables;
- clean-history native/common tables;
- ablations;
- propensity;
- seen/unseen и supported/unsupported aggregates;
- paired CI;
- coverage;
- отдельное решение по каждой гипотезе: `confirmed`, `rejected` или `inconclusive`, с машинно-читаемой причиной;
- итоговое selection decision.

Только агрегаты, без keys и row-level predictions.

### `research_summary_ru.md`

Кратко и понятно для команды:

- baseline ladder;
- shortcut ablations;
- clean-history sensitivity с раздельными native/common результатами;
- propensity;
- unseen/support gates и coverage;
- что подтверждено, отклонено или осталось неопределённым;
- текущий кандидат и ограничения.

Не называть proxy физической поломкой и не называть pre-2025 folds финальным тестом.

### `REPRODUCE.md`

На русском: accelerator None, Add Input, Run All, режимы, ожидаемые RAM/время, расположение четырёх результатов и что вернуть команде.

Не создавать `replicate_team.py` и дополнительные deliverables.

## 11. Acceptance tests

До передачи проверить:

- Restart and Run All проходит на synthetic fixture;
- smoke mode не читает 2025 H2;
- full mode выполняет SHA/schema preflight;
- изменение будущего target не меняет более ранний propensity;
- пропущенные channel-days не становятся implicit negatives;
- все модели прямого сравнения используют одинаковые validation-строки;
- native/common clean-history результаты разделены;
- support gates используют только pre-validation labels;
- categories, calibrator, threshold и `m` не используют validation;
- выходы не содержат `d_channel_key`, `d_object_key`, raw identifiers или row-level predictions;
- CPU preflight и версии библиотек записаны в JSON.

## 12. Stop conditions и запреты

Немедленно остановиться и сформировать диагностические результаты при:

- несовпадении manifest/schema/hash/row count;
- отсутствии точных target-boundary полей;
- невозможности воспроизвести M0;
- неоднозначности causal propensity, которую нельзя разрешить из текущего panel;
- необходимости читать raw data, 2025 H2, 2026 или скачивать внешние данные.

Не изменять backend/API, четыре исходных model notebooks, panel или manifest. Не выдавать гипотезу за доказанный вывод.
