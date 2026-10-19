# Итог интеграции UI и COMBINED v1.1 — 19.10.2026

Ветка **release/final-rc**. Исходное фактическое состояние14aad86 (указанный
в запросе b7e1bc9 уже был предком). Полный проверенный интеграционный код:
**69afb1635577d9dc8d6aeefff6d0edcd71e581eb**. Заключительный commit содержит
только тест навигации и документацию/evidence. Его точный SHA определяется
`git rev-parse origin/release/final-rc`; hash нельзя записать внутрь самого commit.
Main, designer branch и опубликованная история не изменялись. Final tag не создан.

## Commits и поставка

Все перечисленные блоки проверены и опубликованы обычным push в release/final-rc:

| Commit | Результат |
| --- | --- |
| d3e0c240b212c1ada49e6cd63ea2ae983623d92b | Проверенная командная UI-интеграция, прокрутка импорта, co-author дизайнера |
| 95c6859754a350f669e09c91ce37d4965eec474c | Изолированный runtime, backend/schema/API новых сценарных модулей; default OFF |
| 548955a523d46933efea81b6b2c4520834cbb0e4 | Точная передача float/null без округления pandas JSON; fingerprint версии адаптера |
| 69afb1635577d9dc8d6aeefff6d0edcd71e581eb | Карточки, ручная review/draft, исправление гонки истории импорта, evidence |

Заключительный test/docs commit7c4b1cc опубликован; следующий точечный test-only
блок устраняет выявленную CI-гонку чтения стиля временной строки (5локальных
повторов PASS, build PASS). Ни приложение, ни требование >=14px не менялись.
Подробности и неудачный run сохранены в ci-typography-race.json.
Все4jobs реального CI на69afb16
**PASS**: backend, frontend, containers, combined-runtime.
[Run39271828046](https://github.com/goleryt/LDT_MISIS_LOLIPOP/actions/runs/39271828046),
[точные jobs/steps](evidence/combined-v1.1/github-ci.json).
Итоговый tip проверяется ещё одним фактическим run после push; его результат
выдаётся в финальном отчёте, без бесконечного создания commits ради собственного SHA.

Полный [перечень изменённых файлов](evidence/combined-v1.1/changed-files.txt)
относится к diff от14aad86 и включает намеренно сохранённую неизменную поставку ZIP.

## Командная ветка и реальные дефекты

Изучены оба коммита6d4035f/f4e06d7, все12 изменённых файлов, merge-base14aad86.
Перенесены согласованные изменения9файлов: compact menu/focus, карта/URL,
локализация карточек, disclosure/select alignment, import controls/scroll.
Отклонены Settings portal/fixed overlay: x=0/z-index900 закрывает sidebar и
выходит из theme/focus области. Авторские PASS из чужого отчёта не перенесены.
[Подробный review](DESIGN_BRANCH_REVIEW_2026-10.md).

1. **Импорт не прокручивался:** viewport-height workspace обрезал flex-child,
   а route не имел вертикального scroll owner. Добавлен overflow-y:auto в Imports.
   До исправления реальный wheel не достигал30-й строки; после8/8PASS на четырёх
   размерах и обеих темах, включая возврат из Settings. scrollIntoView не служил доказательством.
2. **Гонка истории импорта:** старый GET мог перезаписать новый refresh после upload.
   Generation guard и cleanup допускают только последний ответ; regression реально
   завершает старый HTTP500 после успешного нового ответа. Loading/error/retry PASS.
3. **Сериализация модельного дневного снимка:** pandas JSON округлял float до10знаков.
   Передача Python float/null сохраняет точность без изменения модели/признаков;
   реальный runtime сохраняет parity<1e−12 с поставкой.
4. **Неподтверждённая химическая подпись:** bundle задаёт общий газовый датчик,
   процентный порог1%, но не отдельный контракт H₂/CH4. Исправлено только название
   в UI, не target/units/математика/очередь.

Map Back/Forward/reload, object/sensor URL, compact panels, Escape/focus/resize
подтверждены отдельным Chrome test1PASS. Старые gas→draft, alarm→sensor сохранены.
[UI acceptance](UI_BUGFIX_ACCEPTANCE_2026-10.md).

## Реально запускаемые модели и backend/UI

Старый Gas G2 v3 остаётся в прежнем runtime/очереди, окно[D+2,D+3), proxy.
Новый отдельный Python3.12 runtime реально запускает поставленные Sensor Failure
и Fire v4, окно[D+3,D+4),33дневных суток; обучение/пороги/калибровка не менялись.
Реальный поставленный combine_evidence связывает независимые результаты и правила,
не усредняет оценки и не вычисляет общую вероятность аварии.

Снимок/marker, версии, валидированные forecasts и raw worker outputs хранятся
раздельно. Повтор не дублирует, исправленный источник требует новую snapshot_version.
Неизвестная привязка/нехватка истории → abstain, а не ноль. Исторических интервалов
привязки в текущем справочнике нет: требуется подтверждение catalogue на дату D.
Cooldown3суток применяется отдельно по типу/сущности, без подавления других прогнозов.

Карточки SF и Fire показывают **сценарную оценку0–1**, синтетический/экспериментальный
бейдж, версии, время Москвы, окно, причины недоступности, рекомендации.
Несколько прогнозов видны одновременно. Отдельные ручные review→draft→new работают
с audit/history/idempotency. Автоматических заявок и critical alerts нет.

| Артефакт | SHA256 |
| --- | --- |
| COMBINED_EVIDENCE_V1_1.zip | 1afb9615c2526b21f7aa5e9dd0147b82a74777c86b7c5064b6134dcd0366573b |
| Gas bundle, обе копии идентичны | 1747b09c0a289f8509b1ef066442936f315c4f7958d1815825a7f90296503e20 |
| Sensor integrated v2 ZIP | a5cf7b2d9034cc27108992b6541eb4c9603b870cd5f36dde81ea4c963f5daccb |
| Fire v4 model.json | 3887d5c8663cde8c2e634fa15cdcca36a8da498df6e1ba80e9518fbe4d3d6830 |

Версии Sensor7b3cdb7… и Fire607e63fb… целиком зафиксированы в registry/acceptance;
98manifest файлов проверены. [Архитектура, точные версии и flags](ML_COMBINED_INTEGRATION_RU.md).

## Фактические проверки

| Проверка | Результат / evidence |
| --- | --- |
| Backend |129PASS/4warnings;20focused scenario tests после транспортной правки; backend.xml |
| Security/RBAC |401anonymous,403wrong role/CSRF, allowed200;5ролей, audit/logout; isolated-api.json |
| Frontend | TypeScript/Vite PASS; lint0errors/10существующих warnings; frontend-checks.json |
| Chrome155,Windows |26PASS/5opt-in skips; focused13PASS; gas/mock2PASS; scenario→draft→newPASS; navigation1PASS |
| UI | Светлая/тёмная темы,1024/1280/1440/1920;51PNG, matrix.json; no pageerror/overflow в проверенных сценариях |
| Runtime | Реальный поставленный verifier;810raw synthetic rows;2SF+1Fire, parity/order/future/invalid/missing/off checks PASS |
| New DB/API | Реальная запись3forecasts, повтор reused=true; отдельный gas расчёт1row/1shadow prediction; ручные заявки |
| Alembic | d01901 fresh upgrade; disposable downgrade d01602→upgrade→check PASS; production не затронут |
| Docker | Worker+cloud build, NEW QA PG/startup/health/ready PASS; docker-summary.json |
| Reports | PDF1страница, кириллица; XLSX открывается; isolated-api.json |
| Backup новой схемы |20941events/1scenario run/3forecasts/5requests, checksum+restore НОВОЙ DB+API PASS; backup-restore.json |
| Resource sample |1536MiB/2CPU limit; acceptance около218MiB peakRSS/7–11сек; runtime-acceptance.json |

Результаты небольшого QA не являются нагрузочным тестом полного промышленного
архива, новым RTO или гарантией ресурсов Railway. Старый gas runtime не обновлялся.

Примеры [до исправления](evidence/combined-v1.1/ui/imports-before-dark-1024.png),
полная [визуальная матрица](evidence/combined-v1.1/ui/matrix.json),
[новые dark cards](evidence/combined-v1.1/ui/dark-1280-scenario-cards.png).

## Railway, flags, ограничения и откат

Публичный HTTPS /,/health,/ready200. Authenticated application identifier по-прежнему
**14aad86414826c59857cbc2766d10f48a0b43ba4**. Новые модели в Railway НЕ deployed/enabled;
production migration/secret/tariff не менялись. Новая версия проверена в отдельном
QA на127.0.0.1:18090. [Public evidence](evidence/combined-v1.1/public-status-unchanged.json).

SCENARIO_ENABLED=false по умолчанию. В изолированном demo overlay master=true,
SCENARIO_SENSOR_ENABLED=true и SCENARIO_FIRE_ENABLED=true. Production дополнительно
требует SCENARIO_ALLOW_PRODUCTION=true. Flood/Intrusion/System Failure отключены.
Безопасный откат: выключить master/отдельную голову и остановить только новый
scenario worker; сохранить таблицы/историю/заявки, не downgrade production.
Существующий gas продолжает работать. Полная процедура в integration doc.

Качество НЕ промышленное: baseline19синтетических объектов/9heldout.
SF P56,3/R30,1/Coverage50,2%; Fire P18,2/R13,3/Coverage57,9%.
Overlap SF TP0,FN30,Recall0: отрицательный результат подтверждён поставленным
отчётом; сам полный стресс-расчёт заново NOT TESTED, исходного cache/cohort нет.
Реальная точность инцидентов не установлена; operational_ready=false,
automated_action_allowed=false. Никакого нового ансамбля/подбора порогов.

NOT TESTED/manual: нативный Яндекс, физический touchpad, настоящий browser zoom125/150,
полный архив/целевая инфраструктура/AD/боевые интеграции; новый production rollout.
MISSING FINAL ARTIFACT: актуальная презентацияPPTX/PDF и accompanyingDOCX/PDF.
Эти ограничения не скрываются техническими PASS. Дальнейшие функции не добавлялись.
