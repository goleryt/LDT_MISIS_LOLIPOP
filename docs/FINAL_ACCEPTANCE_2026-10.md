# Финальная приёмка RC — локальный baseline и удалённая проверка 19.10.2026

> Новое дополнение19.10: [дизайнерская ветка](DESIGN_BRANCH_REVIEW_2026-10.md),
> [прокрутка импорта/UI](UI_BUGFIX_ACCEPTANCE_2026-10.md),
> [техническая приёмка новых сценарных модулей](ML_COMBINED_ACCEPTANCE_RU.md).
> Полный код69afb16: [CI39271828046](https://github.com/goleryt/LDT_MISIS_LOLIPOP/actions/runs/39271828046)PASS, все4jobs.
> Итоговые изменения: [delivery report](DELIVERY_COMBINED_2026-10-19.md).
> Свежий локальный backend129PASS, новый head d01901. Публичный Railway остаётся
> на предыдущей версии14aad86; новые сценарные модули production не включены.
> Remote результаты ниже относятся к предыдущей опубликованной версии и не
> доказывают remote-приёмку COMBINED_EVIDENCE_V1_1. Реальное качество аварий не установлено.

> Исторический remote результат для версии до COMBINED: [REMOTE_RC_ACCEPTANCE_2026-10-19](REMOTE_RC_ACCEPTANCE_2026-10-19.md).
> GitHub Actions PASS на `ee16251`, RC опубликован на существующем Railway, миграция
> `d01602`, Chrome/auth/RBAC/заявки/импорт/отчёты PASS. Integration worker, scheduler
> и автоматический backup в Railway отсутствуют; native Yandex/physical touchpad NOT TESTED.
> Таблица ниже сохраняет локальные результаты октября с обновлёнными remote строками.
> Дополнительно исправлена и проверена удалённо ошибка UTC-даты отчёта (`d4f3e09`):
> после московской полуночи выбирается текущий локальный день; local Chrome 16 PASS / 4 opt-in skips.
> После стабилизации ожидания detail refresh весь CI также PASS на `6ca2a44`:
> [run39175260469](https://github.com/goleryt/LDT_MISIS_LOLIPOP/actions/runs/39175260469).
> Повтор b6c488b выявил оставшуюся гонку теста. Финальная правка берёт request_id из
> успешного RPC вместо изменчивой видимости DOM; 3 serial delayed-detail repeats PASS.
> Полный CI и deployed SHA окончательного HEAD фиксируются в итоговом delivery report.

> Это снимок полной приёмки 16.10.2026. Последующий точечный UI-проход,
> опубликованные commits, свежие Chrome/build результаты и ограничения 18.10.2026:
> [UI_BUGFIX_ACCEPTANCE_2026-10-18](UI_BUGFIX_ACCEPTANCE_2026-10-18.md).
> Старые утверждения ниже о непубликации RC относятся к состоянию на 16.10 до разрешённого push.

Ветка **release/final-rc**. Исходные 11 коммитов до `a5ba6e0` сохранены с теми же
hashes; переименована только ветка. Исторический локальный baseline: **f7d1d05**;
основной удалённый прогон после UI-исправлений: **ee16251**;
последующая точечная правка периода отчёта: **d4f3e09**.
Итоговый HEAD: `git rev-parse HEAD`. Ветка опубликована, demo обновлён.
Main и пользовательский checkout не менялись.

Нормативный источник: [8. ДЖКХ.pdf](<8. ДЖКХ.pdf>), 16 страниц.
[Решения владельца](FINAL_SCOPE_DECISIONS_RU.md) применены без ожидания жюри.
ML полностью заморожен: предметная математика, признаки, target, thresholds,
calibration, shadow/abstain, scheduler и бандлы не менялись.
[Проверка diff](evidence/release-rc/ml-frozen.txt). Нового inference на этапе RC не было;
UI использовал настоящий ранее сохранённый результат из восстановленного snapshot.
Fixture unit tests не считаются результатами inference или оценкой качества модели.

Статусы: PASS — подтверждено в указанном объёме; PARTIAL — подтверждено частично;
NOT TESTED — не проверено; EXTERNAL DEPENDENCY — нужна внешняя инфраструктура/данные;
NOT APPLICABLE — исключено зафиксированным решением этого этапа.
PASS контракта не является промышленной сертификацией или общим выполнением ТЗ.

## Свежие результаты RC

| Проверка | Actual result | Evidence |
|---|---|---|
| Полный backend | **108 passed**, 4 dependency deprecations, 76.14 с; Python3.14.6, отдельный PostgreSQL16, test DB | [pytest](evidence/release-rc/backend-final.txt), [JUnit](evidence/release-rc/backend-final.xml) |
| Frontend | TypeScript/Vite PASS; npm ci в cloud build; lint 0 ошибок / **10 warnings** set-state-in-effect | [build](evidence/release-rc/frontend-build.txt), [lint](evidence/release-rc/frontend-lint.txt) |
| Chrome155.0.8059.84 / Windows11Home10.0.26200 | 11 PASS одним прогоном; после визуальных правок 3 PASS; дополнительно 4 PASS на локальном HTTPS с production auth settings | [Chrome](evidence/release-rc/chrome.txt), [visual](evidence/release-rc/visual-final.txt), [HTTPS](evidence/release-rc/chrome-tls.txt) |
| Visual QA | 30 desktop-снимков 1280/1440/1920, dark/light; long Russian text; overflow/pageerror проверены автоматически, выбранные снимки просмотрены | [matrix](evidence/release-rc/visual/matrix.json), [карта/датчик](evidence/release-rc/visual/1280-9.png), [prediction](evidence/release-rc/visual/1280-6.png), [заявки](evidence/release-rc/visual/1440-4.png), [отчёт](evidence/release-rc/visual/1440-7.png), [drawer](evidence/release-rc/visual/long-name-drawer.png), [уведомление](evidence/release-rc/visual/long-notification.png) |
| Alembic | current=heads=d01602; check: no new operations; чистые новые PG/volumes проходят миграции | [check](evidence/release-rc/migrations-current.txt), [clean startup](evidence/release-rc/reproducible-cloud-startup.txt) |
| Cloud Docker | root multistage build + npm ci/build, uid10001, read-only QA, private API, nginx, Tini; новые PG/backup volumes, 20000 synthetic events → smoke PASS | [build](evidence/release-rc/cloud-build-final.txt), [portable smoke](evidence/release-rc/reproducible-cloud-smoke.txt), [lifecycle](evidence/release-rc/cloud-lifecycle-final.txt), [ранний stop](evidence/release-rc/cloud-init-stop.json) |
| Сборка зафиксированного application commit | f7d1d05, build → healthy → smoke → 3 Chrome flows PASS | [commit](evidence/release-rc/application-commit.txt), [build](evidence/release-rc/cloud-build-commit.txt), [smoke](evidence/release-rc/cloud-commit-smoke.txt), [Chrome](evidence/release-rc/chrome-commit.txt) |
| TLS/auth | /health,/ready200; Secure cookie не отправляется по HTTP; CSRF403, admin403 для dispatcher, logout200 →401 | [native HTTPS](evidence/release-rc/tls-security.json) |
| Load | **918 requests / 0 errors**, 1user/20read/20mixed; p95 read471.094мс / mixed448.224мс; p99 535.855/558.283мс; RPS88.216/93.549 | [JSON](evidence/release-rc/load.json), [before](evidence/release-rc/load-stats-before.txt), [after](evidence/release-rc/load-stats-after.txt) |
| Backup/restore | checksum OK; свежий dump → **новая** ldt_rc_restore_verify; **200371 событий**, d01602, restore3с; API smoke PASS | [backup](evidence/release-rc/backup-current.txt), [restore](evidence/release-rc/restore-current.txt), [API](evidence/release-rc/restored-current-smoke.txt) |
| Автокопия после migrate | До исправления первый dump имел 0 schema entries; после — 3, в том числе на новых volumes | [до](evidence/release-rc/initial-auto-backup-schema.txt), [после](evidence/release-rc/auto-backup-clean-schema.txt), [startup](evidence/release-rc/auto-backup-clean-start.txt) |
| Worker | Все 5 mock sources: cursor367, last_success есть, last_error=null; JSON/schema/cursor/timeout/500/connect/retry/idempotency в suite | [live](evidence/release-rc/live-integrations.txt), backend-final |
| Scheduler | Живой frozen scheduler без ready marker: waiting_for_marker, last_success=null; predictions остаётся1. Затем QA scheduler остановлен | [heartbeat](evidence/release-rc/scheduler-waiting.txt), [исходное число](evidence/release-rc/ml-count-before-scheduler.txt) |
| Старый публичный demo | HTTPS root/health/ready200, anonymous auth/me401; это не новый RC | [public-demo](evidence/release-rc/public-demo.json) |

Короткий load не является endurance/SLA. Раньше p95 был284.264/274.828мс; теперь
на cloud nginx +4API workers и восстановленной БД измерено примерно +65.7%/+63.1%.
Конфигурация/фоновые контейнеры отличаются; это сравнение наблюдений, не доказанная
причинная регрессия API. Локальные snapshots CPU/RAM не являются peak-профилем.
DB pool endpoint отражает один процесс, не агрегат всех workers. Промышленный архив
и целевая инфраструктура не измерялись. Повторная оптимизация без установленного SLA не выполнялась.

## Requirement matrix

Команды от корня; pytest из backend, только ENVIRONMENT=test / отдельная ldt_test.
Нельзя запускать fixture suite против demo/production: fixtures очищают тестовые таблицы.

| Requirement | Status | Implementation | Verification / Command/test | Actual result / Evidence | Known limitation |
|---|---|---|---|---|---|
| Backend regression / import | PASS | backend/tests, app.main | python -m compileall -q app scripts; pytest -q | 108PASS, backend-final | 4 предупреждения зависимостей |
| Frontend regression | PASS | frontend/src, e2e | npm ci; npm run build; npm run lint; npx playwright test | build +11Chrome PASS; logs выше | 10 lint warnings; не все сочетания состояний/ролей |
| Clean deployment | PASS | infra/Dockerfile.cloud, compose.cloud-qa.yaml | build → compose up → migrate → seed → smoke | новые volumes, 20000 events; reproducible-cloud-* | Локальный Docker, dependency cache; Railway отдельно |
| Health/readiness | PASS | ready.py, operations.py, start_cloud.py | test_ready, test_rc_diagnostics; /ready | DB/schema check, app version/commit, backup corrupt metadata guard | Heartbeat не мониторинг процесса; pool одного worker |
| Заявки / конкурентность | PASS | requests.py, RequestReview.tsx, d01601 | test_request_drafts; test_request_concurrency; Chrome draft | draft→new→in_progress→completed/cancelled; история/actor; два потока200/409 | Legacy REST без expected_updated_at не защищён от устаревшей последовательной правки |
| Prediction→recommendation→draft | PASS | predictions.py, PredictionsPage.tsx | RUN_ML_E2E=true playwright | Сохранённый настоящий результат→decision→draft→confirmation; URL/refresh/Back | Не новый inference; качество модели не оценивалось |
| Карта→объект→sensor/history | PASS | SchematicMap, ObjectDrawer, MapPage | Chrome map/navigation tests; test_workflows | tooltip/pan/zoom/reset/deep link/фильтры/легенда | Point/fallback; условные координаты маркированы |
| UI loading/empty/error/success | PARTIAL | pages, SessionGate, ErrorBoundary | workflows.spec/release.spec, UI_STATE_AUDIT | Нет pageerror/overflow/undefined/NaN в проверенной матрице; error recovery | Не все комбинации каждого экрана/темы/роли/125-150% |
| Notifications | PASS | Notifications.tsx, notifications API | test_security_acceptance; polling race Chrome | read/personal state, дедупликация, ссылка, recovery; старый poll не возвращает прочитанное | Длительный offline/endurance не проверен |
| Backend RBAC/security | PASS | security.py, auth.py, dependencies | test_security_acceptance, test_workflows, TLS native | manager/technician/dispatcher/analyst/admin,401/403/expiry/logout/CSRF | manager=viewer; корпоративные политики отдельно |
| Audit | PASS | middleware, AuditEntry, decision/request history | security/drafts/workflows tests | actor/role/time/action/entity/result; no credential bodies | Защита от администратора БД/SIEM внешняя |
| CSV/XLSX/JSON/XML imports | PASS | ingestion/import_registry, imports API | test_import_acceptance, test_workflows | valid/duplicate/schema/partial-invalid/oversized/interrupted/retry/atomic rollback | Не весь исходный промышленный архив |
| GeoJSON/WKT | PASS | geo.py + importer | test_real_geo_and_schematic_fallback | реальные Point + честный условный fallback | Геоданные заказчика отсутствуют; линии/полигоны не придуманы |
| Mock integrations | PASS | integration_worker, adapters, mock_source | integration_acceptance, worker_malformed; Compose --profile mocks | 5 контрактов и live cursors; source→DB/API/UI в Chrome | Mock-work live без ID пустой; переход статуса покрыт unit/integration tests |
| Reports PDF/XLSX | PASS | reports.py, ReportsPage | test_reports; Chrome download | Кириллица/метаданные/период/source/rowcount/empty/truncation/формулы | Большой5050→5000 тест ранее на a5base, код отчёта в RC не менялся |
| Backup/restore | PARTIAL | backup.sh, restore.sh, Compose depends_on | backup → verify-restore → smoke | 200371events,checksum,3с,newDB; авто после migrate | Offsite, полный12лет, нормативный RPO/RTO не доказаны |
| Operational scheduler | PARTIAL | frozen ml_scheduler, worker_heartbeats | запуск без marker + DB snapshot | waiting_for_marker, без новых predictions | Successful inference этим этапом не запускался; last_success отсутствует |
| Performance ≥20users | PASS | tests/load.py | 1baseline/20read/20mixed | 918req,0errors; load.json | Короткий локальный профиль; не промышленный SLA |
| Chrome | PASS | Playwright channel=chrome | workflows + release tests | Chrome155,11+3+4 повторных проверки | Локальный QA, не новый remote RC |
| Яндекс.Браузер | NOT TESTED | playwright YANDEX_BROWSER_PATH | BROWSER_ACCEPTANCE_RC checklist | Исполняемый файл/registry не найдены | Требуется нативный запуск человеком |
| Remote RC smoke | PASS | cloud packaging / DEPLOYMENT_RC | native Chrome + direct REST на Railway | 14 browser checks, 5 ролей, drafts/history, JSON import, PDF/XLSX; [remote acceptance](REMOTE_RC_ACCEPTANCE_2026-10-19.md) | Yandex/physical touchpad отдельно NOT TESTED; другие форматы import проверены в isolated QA/CI |
| Railway конфигурация | PARTIAL | cloud nginx, existing PostgreSQL, pre-deploy upgrade | runtime commit, d01602, TLS, health/ready, off-host backup checksum | Web/DB/миграции PASS; [runtime](evidence/release-rc/remote/runtime.json) | Постоянные worker/scheduler/автоматический backup не развёрнуты; бесплатный trial ограничен |
| LDAP/LDAPS | EXTERNAL DEPENDENCY | существующий adapter | test_ldap_contract | verified TLS/read_only/no referrals/no fallback | Реальный AD/bind/CA/группы отсутствуют |
| Промышленная интеграция/архив/география | EXTERNAL DEPENDENCY | GET adapters, Point import | INTEGRATIONS + заказчик | Контракт и mock подтверждены | Нужны endpoints/credentials, реальные данные и координаты |
| Полное прогнозирование ТЗ | PARTIAL | существующий frozen gas contour | ML_INTEGRATION_RU; unchanged diff | Смысл shadow сохранён; не вероятность аварии | Новые модели/классы/сезонность/retraining вне этапа |
| Новые каналы/политики/GIS/retraining | NOT APPLICABLE | фиксированные решения владельца | FINAL_SCOPE_DECISIONS_RU | Не добавлены | Это не утверждение выполнения спорных буквальных пунктов ТЗ |
| Документация | PASS | README, ARCHITECTURE/SECURITY/INTEGRATIONS/COMPLIANCE | link check + evidence inventory | Актуальная локальная RC поставка отделена от старого demo | accompanying DOCX/PDF отдельно отсутствует |
| Материалы финала | PARTIAL | FINAL_ARTIFACTS_RC | inventory | Git/live demo есть; architecture/evidence/deploy/checklist есть | Presentation и актуальная DOCX/PDF — MISSING FINAL ARTIFACT |

## Исправленные реальные проблемы

- Последовательная/одновременная устаревшая правка заявки могла затереть решение:
  добавлен optional version contract +409; UI передаёт версию, сохранена история.
- Обновление списка могло оставить старые поля формы с новой версией: review remount по updated_at.
- Повреждённая backup metadata ломала diagnostics: строгая проверка JSON/aware timestamp.
- Неверный integration envelope/missing cursor мог упасть или сбросить progress:
  валидация до ingestion и recovery tests.
- Старый polling мог вернуть прочитанное уведомление; повторный submit: tombstones/pending guard.
- Prediction detail терял выбранный ID при refresh/Back, устаревшие fetch:
  URL state, отмена запроса, loading и безопасный error.
- Тёмная ссылка/календарь и длинное уведомление были плохо читаемы: локальная CSS-правка.
- Backup стартовал раньше migrate: исправлена зависимость, первый чистый dump содержит схему.
- Ранний SIGTERM контейнера с Python PID1 мог зависнуть до kill137:
  Tini, повторный ранний stop143 за0.72с без forced kill; готовый stop0.

Тестовый внешний TLS-proxy после пересоздания upstream использовал старый IP;
перезапуск собственного QA proxy восстановил /health и повторный security smoke.
Это ограничение локального тестового edge, не заявление о дефекте Railway.

## Что осталось проверить человеку / внешние зависимости

1. Нативный Яндекс и оставшиеся сочетания тем/масштабов/ролей: [browser checklist](BROWSER_ACCEPTANCE_RC.md).
2. Разрешённая публикация RC на существующий demo и полный основной remote flow выполнены.
   Постоянные worker/scheduler/backup остаются отдельной эксплуатационной задачей;
   неизвестные production secrets и тариф не менялись. [Инструкции](DEPLOYMENT_RC.md).
3. Данные/координаты/полный архив, AD/CA/группы, промышленный источник, SIEM,
   offsite backup и измерения на целевой инфраструктуре — заказчик.
4. PPTX/PDF и актуальная accompanying DOCX/PDF, публичные права и зафиксированный
   final commit: [FINAL_ARTIFACTS_RC](FINAL_ARTIFACTS_RC.md).
5. Устаревшие облачные credentials/ранее раскрытые токены ротировать у владельца;
   RC не переписывал Git-историю и не менял production secrets.

Ни один пункт не ждёт уточнения жюри. Невыполненное обозначено по фактической причине.
Сентябрьские документы и [октябрьский baseline](evidence/2026-10-16/backend-final.txt)
сохранены как история; MAP_TZ_COVERAGE_RU явно HISTORICAL/SUPERSEDED.
Большой report/backup failure/rotation/TLS1.1 rejection из первого этапа остаются
действительными проверками неизменённых компонентов, но не называются свежим RC прогоном.

Полный перечень commits и файлов: [CHANGE_MANIFEST_2026-10](CHANGE_MANIFEST_2026-10.md).
Evidence не содержит паролей/cookies/токенов; browser traces в Git не добавлялись.
Локальные ссылки и известные token/private-key signatures проверены автоматически:
[document-check](evidence/release-rc/document-check.json). Сигнатурный scan не доказывает
отсутствие всех возможных типов секретов. Удалённый GitHub Actions **PASS**:
[run 39173000415](https://github.com/goleryt/LDT_MISIS_LOLIPOP/actions/runs/39173000415),
backend/frontend/containers, commit `ee16251`. Два дефекта тестовых селекторов/данных
исправлены без отключения полезных проверок; детали в remote acceptance.
