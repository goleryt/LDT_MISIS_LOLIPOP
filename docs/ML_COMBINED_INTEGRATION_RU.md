# COMBINED_EVIDENCE_V1_1 — отдельный экспериментальный контур

Поставка от19.10.2026 подключается без изменения существующего газового runtime,
его зависимостей, feature engineering, target, калибровки, очереди и истории.
Исходный ZIP хранится неизменным в `ml_combined/`; `unpack.py` проверяет внешний
SHA256, все98 файлов и копии registry/requirements до извлечения. Вложенные модели
содержат JSON/LightGBM text, а новый контур не загружает pickle.

## Идентичность и смысл

| Артефакт | SHA256 |
| --- | --- |
| COMBINED_EVIDENCE_V1_1.zip | `1afb9615c2526b21f7aa5e9dd0147b82a74777c86b7c5064b6134dcd0366573b` |
| gas_cross_v3_bundle.zip: существующий и поставленный | `1747b09c0a289f8509b1ef066442936f315c4f7958d1815825a7f90296503e20` |
| incident_sensor_integrated_v2.zip | `a5cf7b2d9034cc27108992b6541eb4c9603b870cd5f36dde81ea4c963f5daccb` |
| fire_candidate/model.json | `3887d5c8663cde8c2e634fa15cdcca36a8da498df6e1ba80e9518fbe4d3d6830` |

Gas: `gas-cross-g2-v3-refit_2025h1-0312ff1f436e`, feature contract
`event-panel-v3.0+tax-c95e75ea+g2-5cc9a364`, target
`gas_threshold_cross_1pct_d2_proxy_v3`, порог наблюдения1%, окно[D+2,D+3),
Europe/Moscow, примерно400 суток событий. Bundle побайтно идентичен; замены нет.
Поставка называет контур «H₂», но проверенные contract/taxonomy описывают
«Газовый датчик» и процент, без отдельного контракта измерения водорода.
Обозначение H₂ не интерпретируется как новый газ. Прежняя подпись CH4 в UI также
не подтверждается этими артефактами: отображение уточнено до «газового порога1%»,
без изменения target, значений, единиц входных данных или политики газового worker.

Sensor Failure model version:
`7b3cdb7d09b810841f1ca0553251ef08ef6b5eda3e69bcfbc6de0f25ac7af1c5`.
Fire v4:
`607e63fbc297117c149124913bb51cb8bb5f0e0c247550afdc83873ae830c29e`.
Оба: `incident-rescue-causal-counts-v2`,33 суток наблюдений,[D+3,D+4),E4,
synthetic_scenario/scenario_score. Пороги из неизменного registry не подбираются.

## Процессы, снимки, БД

`ml_combined/Dockerfile`: независимый Python3.12 с точными зависимостями поставки.
API остаётся Python3.14 и не импортирует ML-библиотеки. Отдельный
`scripts.scenario_scheduler` ждёт файл `scenario_YYYY-MM-DD.json`; газовый scheduler
и его текстовый ready-marker остаются прежними.

Marker создаёт доверенный ETL только после проверки полноты. Пример структуры:

```json
{"as_of_date":"2026-10-18","loaded_at":"2026-10-19T06:00:00+03:00","complete":true,"catalogue_valid_as_of":"2026-10-18","snapshot_version":"etl-confirmed-v1","coverage":{"start":"2026-09-16","end_exclusive":"2026-10-19"}}
```

Это пример формата, **не** инструкция объявить неизвестный источник полным.
Producer должен атомарно переименовать готовый marker. Backend проверяет закрытие
суток, timezone/loaded_at, конец coverage и явное подтверждение справочника на D.
Текущая БД не хранит интервалы исторических привязок; неподтверждённый исторический
справочник не следует сертифицировать. Версия и точные использованные строки
справочника сохраняются в неизменяемом входном снимке.

В REPEATABLE READ экспортируются только события[D−32,D+1), без заполнения пропусков.
Предел по умолчанию200000 строк защищает demo от неограниченного экспорта, превышение
даёт явную ошибку. Полнота coverage требует независимого подтверждения источника;
наличие нескольких событий само по себе её не доказывает.

`scenario_runs` хранит снимок, fingerprint, версии, raw output, context и историю
попыток. `scenario_forecasts` содержит только прошедшие combine_evidence строки
новых типов, дополнительно проверенные по версиям, окнам, оценкам и привязкам БД.
Неизвестная привязка превращается в abstain с отсутствующей оценкой.
Успешный повтор fingerprint возвращает прежний run. Исправление снимка требует новой
snapshot_version и создаёт ревизию. Cooldown3суток применяется отдельно к типу и
сущности, не удаляет историю и не подавляет другой тип. Он управляет полем attention,
а не изменяет модельную оценку или правила combine_evidence.

Дочерний `compute.py` получает только JSON-файлы и очищенное окружение без DB/LDAP/
Railway credentials. Есть180сек таймаут, отдельный heartbeat и sanitized error codes.
Передача дневных фактов сохраняет точные finite float и null, без стандартного
округления pandas.to_json до10 знаков. Исправление transport `548955a` не меняет
формулы или артефакты модели; fingerprint включает adapter v1.1 и SHA compute.py.
Используются доставленные `score_journal`, fire wrapper и `combine_evidence`
(`evidence-combination-v1.1`), без усреднения оценок. Газовый payload передаётся
неизменным из существующего MlRun/MlScore, с фактическим finished_at; дата выпуска
не выдумывается. Несовместимая дата/версия worker не блокирует остальные.

Ошибку процесса можно повторить явно `--retry-failed`, сохранив журнал попыток.
Partial/недостаточная история автоматически не пересчитываются: после исправления
источника/worker нужна новая подтверждённая версия marker. Scheduler не запускает
бесконечный inference и не создаёт marker сам.

## Включение и откат

По умолчанию `SCENARIO_ENABLED=false`. При явном demo opt-in Sensor Failure и Fire
включены (`SCENARIO_SENSOR_ENABLED=true`, `SCENARIO_FIRE_ENABLED=true`); остальные
головы недоступны. `operational_ready=false`, `automated_action_allowed=false`.
Для production дополнительно требуется `SCENARIO_ALLOW_PRODUCTION=true` после
отдельной приёмки. На существующем Railway новые flags не включались.

Изолированный demo: к `infra/compose.yaml` явно добавить
`infra/compose.scenarios.yaml`, профиль `scenarios-demo`, использовать отдельную
QA-БД и корректный env. Overlay не входит в стандартное развёртывание. В production
он намеренно не обходит защиту configuration.

```text
docker compose --env-file backend/.env -f infra/compose.yaml -f infra/compose.scenarios.yaml --profile scenarios-demo up --build -d
python -m scripts.run_scenarios --ready-marker /scenario-ready/scenario_YYYY-MM-DD.json
```

Вторая команда выполняется только в новом Python3.12 worker, не в web-контейнере.
`scripts.scenario_demo_fixture` разрешён исключительно для
ENVIRONMENT=test/POSTGRES_DB=ldt_combined_qa, пишет только искусственные исходные
наблюдения; прогнозы рассчитывают настоящие замороженные модели.

Откат: выключить master flag в API и worker, остановить только scenario worker.
При необходимости отключить отдельно Fire/Sensor. Историю сохранять; migrations
и данные не удалять. Газовый worker продолжает работать независимо.

## API и ручные действия

`GET /api/v1/predictions/scenarios`: configuration, безопасная метаинформация runs,
последний/выбранный снимок, фильтр worker и валидированные карточки. Raw snapshot/
worker outputs через этот endpoint не выдаются. Ограниченный список не выдаётся
за полный архив. HTTP inference/изменения порогов не добавлены.

`PATCH /predictions/scenarios/{id}/decision`: revision + monitoring/reviewed/dismissed
и обязательный комментарий. `POST .../{id}/request`: отдельный ручной draft,
идемпотентный по карточке; разные типы не объединяются в одну автоматическую заявку.
Подтверждение draft выполняется старым requests API с его RBAC/history.
Роли/CSRF/audit прежние: admin/dispatcher/analyst могут проверить сценарий; manager
и technician читают. Analyst не получает право подтверждать draft.

Новый worker не пишет реальные тревоги, Notification, газовую очередь или показания.
Диагностика: admin `/api/v1/operations/status`, `scenario_worker`, `last_scenario_job`.

На810 исходных строках runtime занял около218MiB RSS; это не замер полного архива.
Compose ограничивает новый контейнер1.5GiB/2CPU. Для бесплатного Railway безопаснее
отдельный пакетный worker после подтверждения ресурсов, а не установка новых ML
библиотек внутрь web или газового процесса. Промышленная ёмкость/RTO не доказаны.
