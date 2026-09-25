# Последовательность ML-реализации

Дата актуализации: 2026-09-22. План учитывает pre-2025 аудит Claude.

## Главный вывод из аудита Claude

Текущая цель не является физическим отказом и не гарантирует onset в D+2. Она означает:

> в D состояние `Неисправен`/`Обесточен` не наблюдалось, а в D+2 наблюдалось; D+1 может уже содержать это состояние.

Поэтому в API и отчётах используем формулировку `observed failure-state proxy on D+2`, а не «вероятность поломки».

LightGBM лучше ранжирует proxy, но логистическая регрессия даёт больше episode precision и меньше ложных тревог. `no_calendar` — обязательный упрощённый кандидат. Channel propensity пока не прошёл отбор.

## Поток A — временная backend-модель

1. Исправить название/описание цели в model contract и API-документах, не меняя само поле без версионирования.
2. ~~Получить у Claude `05_lightgbm_propensity_research_cpu.ipynb` и `REPRODUCE.md`.~~ Внесены в ветку: `ml/sensor_failure/pre2025_audit_runtime.py`, генератор, `notebooks/kaggle/05_…ipynb`, `docs/REPRODUCE_05_RU.md`, `tests/test_pre2025_audit_runtime.py`. Прогон, результаты которого цитируются выше, был сделан до внесения; повторный FULL-прогон на текущей версии нужен для полной аудируемости.
3. Сравнить на одних validation-строках `logistic`, `M0_lightgbm` и `no_calendar`.
4. Применить gates симметрично ко всем:
   - episode recall @ 50/day, cooldown 72h;
   - episode precision не хуже лучшей простой модели более чем на 1 п.п.;
   - нет материального роста false alerts / 1000;
   - PR-AUC и calibration — вторичные;
   - при статистической ничьей выбирается более простая модель.
5. Упаковать победителя как versioned shadow-model. Backend не показывает score как вероятность физической поломки.

## Поток A1 — цель v2 для основной модели (notebook 13)

Реализованы шаги 1–4 раздела 9 `docs/ML_TZ_BEST_FIT_SOLUTION_RU.md`: строгая onset-цель v2 из panel v2
(без пересканирования архива), причинные cadence-признаки, B0–B4 + LightGBM на rolling-фолдах, E1–E3 с одним
изменяемым фактором. План: `docs/EXPERIMENT_13_EPISODE_V2_RU.md`; запуск: `docs/REPRODUCE_13_RU.md`.
Статус: код и тесты готовы, нужен FULL-прогон на Kaggle CPU. Результат решает, какую цель и какой набор
признаков упаковывать в shadow-модель потока A (шаг 5).

## Поток B — missing-target notebooks 07–12

| Этап | Результат | Владелец | Зависит от |
|---|---|---|---|
| 07 | Версионированные object-day/channel-day proxy панели | Codex | source panel v2 |
| 08 | Access: prevalence, rule, logistic, Deep Sets | Claude | контракт 07 |
| 09 | Fire: rule/logistic, Deep Sets scratch, transfer | Claude | контракт 07 |
| 10 | Flood synthetic challenge + anomaly model | Codex | контракт 07 |
| 11 | Channel dropout: rule, hazard, masked TCN | Codex | контракт 07 |
| 12 | Типизированный scorecard/router без усреднения целей | Codex | outputs 08–11 |

Ноутбуки 08–11 разрабатываются параллельно после фиксации schema 07. Ни Claude, ни Codex не меняют схему 07 односторонне.

## Порядок запуска

1. Static contract tests и синтетический fixture.
2. `07` smoke, затем `07` full на Kaggle CPU; его output публикуется как private Dataset.
3. Параллельно: `08`, `09`, `10`, `11` smoke.
4. После smoke-приёмки: full GPU-запуски 08–11. Никакой подбор по 2025 H2/2026.
5. Codex аудирует outputs и код Claude, прогоняет общие contract tests.
6. `12` собирает scorecard. Цели не усредняются; каждый score сопровождается `score_kind` и `evidence_level`.

## Общие изменения после аудита Claude

- Calendar-признаки по умолчанию исключены.
- Для access/fire обязательны recurrence-бейзлайн и clean-history slice.
- Sensor-composition prevalence — обязательный бейзлайн: тип датчика оказался сильным predictor.
- Если в срезе < 20 positives, метрика/гипотеза имеет статус `not_evaluable`, а не «подтверждено» или «отклонено».
- Отсутствие unseen objects означает «нет оценки», а не нулевую метрику.
- 2021 — только retrospective migration slice, если модель обучена на более поздних годах.
- Deep Sets/TCN/autoencoder выбираются только после симметричного сравнения с простыми бейзлайнами.

## Поток C — доведение до production

1. Получить у заказчика incident/work-order labels, исторический справочник каналов, thresholds/units и lifecycle каналов.
2. Версионировать E0-цели; weak/synthetic labels не переименовывать в incidents.
3. Провести prospective shadow-тест на новом периоде. 2025 H2 и 2026 уже не являются untouched final test.
4. Только после этого модель может управлять реальными операционными решениями.

