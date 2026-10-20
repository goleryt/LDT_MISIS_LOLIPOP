# Доставка командного UI и проверка существующего Railway — 20.10.2026

Ветка `release/final-rc`. Исходный HEAD5f274217cc566ee34b1eac26017041966452643e.
Функциональный проверенный release **18af8fa339c8da54db5337fb6592cb0a87a0dcad**,
[GitHub CI39408268560](https://github.com/goleryt/LDT_MISIS_LOLIPOP/actions/runs/39408268560),4/4 jobs PASS.
[Существующий публичный сервис](https://ldt-demo-production.up.railway.app/),
deployment **b1bd6fee-0e94-46b9-8d76-11b555c8e06f**, SUCCESS; app0.2.0 /18af8fa.

Этот документ входит в следующий evidence-only commit. Его полный SHA, отдельные CI/deployment
и совпадение local/origin/running фиксируются при закрытии этапа; собственный hash нельзя
записать внутрь того же коммита. При финальной публикации проверяется отсутствие runtime diff
с18af8fa. Здесь результаты относятся к явно указанной функциональной версии, не к будущему SHA.

## Commits и источник дизайна

Все изменения опубликованы обычным push только в origin/release/final-rc:

- aa197ef — командный UI, Reports validation и fast Back fix; source credit Марии Мягковой.
- 1bdb8f2 — multi-user/file-size/import/browser evidence и regression probes.
- 18af8fa — CI-only registry fix: точный прежний Python3.12 image digest через Docker Hub.
- Следующий documentation/evidence commit — фактическая remote приёмка и этот отчёт.

Исследованы все11 commits ui/rc-visual-fixes-20261019, tipaec7953,
merge-baseae43e33. Приняты белые Login/Settings/Journal, разные navigation icons,
стабильный единственный background и широкая центральная форма Reports.
Вручную адаптированы native light scheme/focus/placeholder и две колонки дат.
Не перенесены повторный CSS import, unused List и liquid-glass buttons, отменённые автором.
[По каждому исходному коммиту](VISUAL_BRANCH_INTEGRATION_2026-10.md).
Main, командная ветка, опубликованная история и final tags не изменялись.

## Найденные реальные проблемы и исправления

| Проблема | Причина | Исправление / доказательство |
|---|---|---|
| Быстрый Back закрывал sensor panel при правильном URL | Router мог свернуть close/Back в исходный URL, effect не зависел от selectedSensorId; прежний navigation key считался достаточным | Guard сверяет фактическую selection с URL, dependency добавлен; усиленный local и remote тест повторяет fast Back×3 |
| Team TS compile failure | List остался imported после замены трёх иконок | Неиспользуемый импорт удалён; TypeScript build PASS |
| CSS подключался дважды | main.tsx и AppLayout.tsx импортировали white-surfaces | Один global import в main, включая Login до авторизации |
| Подсказки белой Login card недостаточно контрастны | #9b9ba3 на белом | #6b7280; автоматический contrast>=4.5:1, обе темы |
| Native checkbox/date scheme на белой панели мог наследовать dark | Card background изменён, scheme/tokens оставались от страницы | Локальные semantic colors, color-scheme:light, focus outline; lazy Settings→Journal→Settings regression |
| Reports имел несбалансированную раскладку и необъяснимый disabled | auto-fit мог создать третью пустую колонку; invalid period только отключал кнопки | Две равные колонки, явная причина/aria-invalid, existing primary-button; local и remote4 theme/size сочетания |
| CI блокировал публикацию | ECR дважды вернул429 до inference, источник кода не менялся | Docker Hub выдаёт тот же OCI digest; локальная frozen parity PASS и новый фактический CI PASS |

Два вспомогательных UI probe потребовали корректной ready/auth orchestration; это не
скрытые product fixes. Первый map watcher стартовал в момент намеренного QA restart.
Его FAIL сохранён отдельно, затем весь крупный кейс повторён с уже открытой картой.

## Проверки и фактический результат

| Область | Результат | Evidence |
|---|---|---|
| Backend |151 PASS /4 dependency warnings, dedicated test DB | evidence/visual-integration-2026-10-20/backend.xml |
| Frontend | TypeScript/Vite PASS; lint0 errors /10 existing warnings | frontend-build.txt / frontend-lint.txt в том же каталоге |
| Chrome local |33 PASS /8 explicitly optional skips; restored actual-data browser/scenarios отдельно PASS | chrome.json / restored-data-flow.json / restored-scenario-flow.json |
| Visual | Before40; final local136; public136;2 themes ×4 desktop sizes; дополнительные формы4 сочетания;0 page errors | visual-before.json / visual-final-local.json / visual-remote.json / remote-forms.json |
| Screenshots |32 before/after originals и36 curated public screens; credential-filled login и traces не публикуются | evidence/visual-integration-2026-10-20/screens/ |
| Docker / startup | Production image build, новая clean PG18 DB и seed без прогнозов, master OFF; CI compose clean startup | local-gate.json / ci-functional.json |
| Migration | Local upgrade/check и public alembic current d01901(head); новые миграции отсутствуют | local-gate.json / remote-build-identity.json |
| Concurrent imports |5/10/20 users, CSV/XLSX mixed + same files;1000/10000(existing)/25000 rows/file; malformed among valid;8 new cases | IMPORT_VISUAL_SUPPLEMENT_2026-10-20.md |
| Load outcome |1962 normal API /0 failures;500000 new rows per large case; max web408.51MiB; PG working set468MiB; max11 target connections incl.monitor;0 OOM | imports/gate.json и raw samples |
| Live map under load |112 реальных browser iterations с +/- во время подготовки/загрузок;0 runtime errors; отдельная БД | imports/browser-map.json |
| Atomicity / duplicates | Same-file20 users оставляют1000 rows; malformed case19 completed/1 failed/19000 rows; post-load0 leaked transactions/slots/processing | imports/post-load.json |
| Restore | Backup10095982 bytes/SHA73a3fc63…6e5fd; NEW PG18 restore173867 events, schema/API/login PASS | backup-restore.json |
| Actual CI |39408268560 /18af8fa /attempt1 /4 successful jobs | ci-functional.json |
| HTTPS | TLSv1.3, hostname/chain verified, HTTP301→HTTPS; root/health/ready200 | remote-api.json / remote-build-identity.json |
| Login/logout/security |5 real roles,401 anonymous,403 missing CSRF/wrong role, Secure/HttpOnly/SameSite cookie, logout→401 | remote-api.json |
| Map/alarm/navigation | Object/sensor/history, refresh, alarm→exact sensor, resize, wheel, buttons, synthetic pinch/clamp/drawer, fast Back×3 | remote-browser.json |
| Request creation | Полностью заполненная manual form создаёт request11; SF forecast2 создаёт draft12→review→new; history/audit/idempotency | remote-browser.json / remote-scenarios.json / remote-request-audit.json |
| Notifications | PARTIAL: public unread empty, entity transition NOT TESTED; local existing factual alarm notice→entity→read PASS; poll race recovery regression PASS | remote-browser.json / restored-data-flow.json / chrome.json |
| Imports remote | Одна normal labelled JSON demo observation; registry и duplicate PASS. Stress только local | remote-browser.json |
| Reports remote | Browser PDF/XLSX, кириллица PDF извлекается, XLSX читается; date validation visible | remote-report-validation.json / remote-forms.json |
| Current data | CSV source journal169993 preserved;173868 total events,97 objects,11490 channels;3 gas/3 scenario outputs unchanged | remote-build-identity.json |
| Workers / scheduler / backup | Integration and gas scheduler not_observed; scenario completed19.10; automatic backup not_configured | remote-api.json operations |
| Build identity | New index JS/CSS и Map/Reports chunks match running /site bytes; shared session chunk закономерно не изменился | remote-build-identity.json |

Производительность QA и бесплатного Railway напрямую не сравнивалась. CPU sampled max:
web202.07%/PG102.81% одного ядра при выделенных2 vCPU; ordinary API maximum case-p95
528.09ms. PostgreSQL memory.current включает reclaimable file cache и достиг1023.88MiB
при local1GiB; working set существенно меньше. Public limit999997440 bytes, не1GiB.
Это не stress proof20 maximum-size files,12-летнего архива или промышленного RPO/RTO.

## Три контура и ограничения

Gas G2 v3: сохранённые3 shadow/proxy результата; model/score semantics неизменны.
Sensor Failure:2 сохранённых сценарных результата; forecast2 был новым manual draft flow.
Fire v4:1 сохранённый экспериментальный результат; existing request9/history/idempotency
проверены, новый Fire inference/draft не выдумывался. combine_evidence и зависимости
не менялись. Immutable gas/scenario payload hashes совпали до/после публичной приёмки.
В изолированном CI замороженный numeric contract на810 supplier synthetic rows PASS;
это не Precision/Recall и не доказательство качества реальных инцидентов.

SCENARIO_ENABLED/ALLOW_PRODUCTION/SENSOR/FIRE=true сохранились; остальные heads OFF,
operational_ready/automated_action_allowed=false. Никаких automatic critical alerts/requests,
retraining, seasonality, threshold/calibration изменений или public inference ради PASS.

Осталось NOT TESTED / manual action:

- Native Яндекс.Браузер не обнаружен; выполнить BROWSER_ACCEPTANCE_RC.md на текущем SHA.
- Physical touchpad: automated WheelEvent PASS, физический жест проверить вручную.
- Native Chrome Zoom125/150%: viewport/DPR matrix не подменяет native browser zoom.
- Remote notification→entity: нет unread notice; данные ради PASS не создавались.
- Continuous worker/scheduler/offsite backups, customer AD/CA, реальные внешние feeds,
  полный архив и действительная география требуют инфраструктуры/данных заказчика.
- Presentation PPTX/PDF и accompanying DOCX/PDF — MISSING FINAL ARTIFACT.

Rollback: прежний5f27421 application archive и APP_COMMIT на том же web service,
с сохранением d01901/DB/volume/новых записей. Restore dump только в NEW DB, без
автоматического overwrite/downgrade. Подробности в RAILWAY_RELEASE_ACCEPTANCE_2026-10.md.

Код изменён только в6 frontend source files и CI workflow. Regression probes дополнены,
backend/infra/ML source byte-identical исходной проверенной версии. Полный перечень файлов:
[evidence manifest](evidence/visual-integration-2026-10-20/changed-files.txt).
Закрытие этапа после documentation-only commit: отдельный CI, обычный push и rollout,
затем clean git status и local=origin=running commit. Итоговый receipt сообщается отдельно;
main merge и final tag не выполняются.
