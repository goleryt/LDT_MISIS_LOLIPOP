# Приёмка COMBINED_EVIDENCE_V1_1 — 19.10.2026

Ветка: `release/final-rc`; исходный RC `14aad86`, UI-интеграция `d3e0c24`.
Проверки ниже относятся к изолированному QA и замороженным артефактам, а не к
промышленному качеству реальных аварий. Production enablement не выполнялся.

| Требование | Статус | Реализация / как проверить | Фактический результат / evidence | Ограничение |
| --- | --- | --- | --- | --- |
| Целостность поставки | PASS | `unpack.py`; доставленный `verify_package.py` в Python3.12, network none/read-only/no credentials |98 файлов,3 контрольных model hashes; `evidence/combined-v1.1/supplier-package-verification.json` | Не утверждение безопасности произвольного будущего ZIP |
| Старый gas не заменён | PASS | SHA обеих копий1747b09…; существующий отдельный runtime | Реальный газовый расчёт в новой QA-БД:1 gas row,1 shadow prediction; затем gas в combine доступен | Публичный gas не пересчитывался |
| Sensor и Fire запускаются | PASS | `python /opt/combined/acceptance.py /qa` в новом контейнере |2 sensor +1 fire, parity с поставкой<1e−12, исходные810 наблюдений; `runtime-acceptance.json` | Все исходные события искусственные |
| Leakage/order | PASS в пределах fixture | Повтор с обратным порядком и добавлением будущего наблюдения | Оба результата совпадают; тот же runtime evidence | Не заменяет аудит промышленного ETL |
| Missing history/flags | PASS | Реальный runtime, сокращённый coverage, отключение каждой головы отдельно | Недоступно, без нулевого риска; другие модули сохраняются | Нет реконструкции отсутствующей истории |
| Invalid worker/versions/dates/NaN/Infinity/duplicates | PASS | Реальный combine_evidence с намеренно испорченными входами; backend contract tests | Некорректная голова исключена, Fire/gas остаются; `test_scenarios.py`, runtime evidence | Это отрицательные тесты, не рабочие прогнозы |
| Сохранение/идемпотентность | PASS | `run_scenarios` на новом PostgreSQL; повтор того же marker |run1 completed, повтор reused=true;3 scenario rows; `isolated-api.json` | Полный архив не проверен |
| Ревизии/ошибка/recovery | PASS |20 backend scenario tests, recorded REAL output transport fixture | Новый снимок — новая ревизия; timeout→явный retry; журнал ошибок сохраняется; изменённый источник требует новой snapshot_version | Partial retry требует новой подтверждённой версии marker |
| Привязка | PASS для текущей схемы | Registry+snapshot catalogue+дополнительная DB validation | Неизвестная связь → abstain/score=null | Исторических интервалов в текущем справочнике нет; ETL должен подтвердить его валидность на D |
| Backend/security regression | PASS | Dedicated `ENVIRONMENT=test POSTGRES_DB=ldt_test`; `pytest -q` |129PASS,4warnings; `backend.xml`; отдельно20 scenario tests после уточнений | Не тестировалось против production-БД |
| RBAC/CSRF/audit | PASS | Прямой REST пяти ролей и pytest | Anonymous401; manager/technician403 на review; dispatcher/analyst/admin200; без CSRF403; actor/role/entity/result в audit | LDAP/AD промышленно не подключался |
| Миграции | PASS | Fresh DB upgrade→d01901; QA downgrade d01602→upgrade→check | Чистая схема; Alembic check без новых операций | Downgrade только одноразовой тестовой БД, не Railway |
| Chrome и исходные flows | PASS в проверенном объёме | Основной suite и отдельные gas/mock/scenario workflows |26PASS/5opt-in skips; отдельно gas→draft и mock→sensor2PASS; отдельный scenario→review→draft→newPASS | Visual/ordinary draft опции отмечены отдельно |
| UI моделей/light/dark | PASS | Реальные recorded scores, оба theme,1024/1280/1440 |2 card testsPASS, не percentages; raw/rejected scores не показываются; PNG в `ui/` | Нативный browser zoom отдельная ручная проверка |
| Docker/cloud/startup | PASS | Отдельный worker build и standalone cloud build; NEW QA DB и migration перед стартом | Web healthy; /health200,/ready200; API role/report smokePASS | QA deployment, не Railway release |
| Backup новой схемы | PASS в небольшом QA |pg_dump16→checksum→pg_restore в НОВУЮ БД→API smoke |20941events,1scenario run,3forecasts,5requests,d01901 совпали; `backup-restore.json` | Не новый load-test и не RTO промышленного архива |
| Worker readiness | PASS в проверенном объёме | Отдельный scheduler без marker | heartbeat waiting_for_marker, предыдущий успешный batch сохранён; `isolated-api.json` | Не доказывает круглосуточную промышленную эксплуатацию |
| Ручные заявки | PASS | Реальный browser/API, отдельная карточка каждого типа | Явный draft→new, idempotent request_id, история/аудит | Автоматических заявок/критических тревог нет |
| Отчёты/импорт/старый UI | PASS в проверенных сценариях | Chrome request/import/history/report flows, direct PDF/XLSX | PDF1страница с кириллицей, XLSX открывается; основной Chrome suite | Новых модельных метрик в factual reports нет |
| Resource sample | PASS как измерение | Ограниченный контейнер1536MiB/2CPU,810rawrows | Около218MiB peakRSS;7–11сек для acceptance с повторными моделями | Не capacity/RTO полного12-летнего архива |
| GitHub CI | См. отдельный CI evidence | Новый job combined-runtime + прежние backend/frontend/containers | UI commit d3e0c24: [run39266296163](https://github.com/goleryt/LDT_MISIS_LOLIPOP/actions/runs/39266296163)PASS | Новый integration commit проверяется отдельным run |
| Railway новые модели | NOT TESTED / NOT ENABLED | `SCENARIO_ENABLED=false`, production требует отдельного разрешения конфигурации | Не менялся; опубликованная версия предыдущего этапа14aad86 | Это намеренная граница, не завершённый production rollout |
| Native Yandex / physical touchpad | NOT TESTED | Предыдущий manual browser checklist | Нет нативного запуска/физического ввода | Synthetic wheel/pinch не заменяет физический тест |

## Качество отдельно от функциональности

Общий синтетический baseline —19объектов, включая9 исходно отложенных.
Sensor Failure: Precision56,3%, Recall30,1%, Coverage50,2%.
Fire: Precision18,2%, Recall13,3%, Coverage57,9%.
В overlap `sensor_failure/all`: TP0,FN30,matched0/30,Recall0.
Проверено чтением неизменного отчёта: `overlap-limitation.json`.

Набор не содержит исходного реального дневного кэша для воспроизведения всей
исследовательской stress-suite. Поэтому **сам стресс-расчёт заново не запускался**;
его отрицательный результат подтверждён по поставленному отчёту. Полный архив,
реальная точность инцидентов, количественное улучшение gas и промышленная готовность
автоматических действий НЕ установлены. Стек в поставке отклонён на development;
новый ансамбль/пороги/обучение не создавались.

## Повторение и откат

Воспроизведение runtime: Dockerfile `ml_combined/Dockerfile`, затем acceptance.py
без сети/секретов с единственным writable QA-output каталогом. PostgreSQL fixtures
допустимы только в отдельной тестовой БД; обычный pytest её очищает.
Инструкция marker, opt-in flags и безопасный откат без удаления истории:
[ML_COMBINED_INTEGRATION_RU](ML_COMBINED_INTEGRATION_RU.md).

Скриншоты с искусственными данными: `evidence/combined-v1.1/ui/`.
Здесь нет cookies, trace, токенов, DB URL или паролей. Входные синтетические
наблюдения поставки не выданы за промышленную телеметрию.
