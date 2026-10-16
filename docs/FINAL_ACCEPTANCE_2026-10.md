# Финальная приёмка немодельного контура — 16.10.2026

Ветка: `final/non-ml-hardening-20261016`. Исходная origin/main: `5d64126`, чистый новый worktree.
Оригинальная пользовательская папка, main и публичный demo не изменялись; push не выполнялся.
Проверенный application commit чистого развёртывания: `860c15b`; последующие изменения:
`6493c52` — права backup-меток (проверены отдельно), `1c843ad` — тест карты.
Последний application commit — `50cbdd9`: понятные empty/loading/error карты и отчёта, безопасные ошибки API; проверены сборкой и восемью Chrome tests.
Чистая копия обновлена локальным fast-forward до 50cbdd9, frontend пересобран, backup marker проверен; три Chrome tests прошли.
Последующие commits с документацией/evidence не меняют исполняемое поведение.
Точный итоговый HEAD показывает `git rev-parse HEAD`.

Нормативный источник: [официальное ТЗ](<8. ДЖКХ.pdf>), 16 страниц.
Файл TZ_FINAL_REVIEW_AND_NON_ML_QUESTIONS_RU.md в текущей поставке не найден.
Решения владельца после консультации: [FINAL_SCOPE_DECISIONS_RU](FINAL_SCOPE_DECISIONS_RU.md).
Ожидания ответа жюри больше нет.

Статусы: **PASS** — проверено в указанном объёме; **PARTIAL** — часть подтверждена;
**NOT TESTED** — не проверено; **EXTERNAL DEPENDENCY** — нужны внешние данные/инфраструктура.
**OUT OF SCOPE (FIXED DECISION)** — исключено прямым решением владельца, без ожидания уточнения.
PASS локального контракта не означает промышленную сертификацию.

## Свежие результаты

| Проверка | Фактический результат | Evidence |
|---|---|---|
| Backend compile/import + pytest | 82 passed, 4 предупреждения зависимостей, 40.11 с; Python 3.14.6, отдельный PostgreSQL 16 | [backend-final](evidence/2026-10-16/backend-final.txt), [JUnit](evidence/2026-10-16/backend-final.xml) |
| Alembic | Пустая БД → d01602; current=heads; check без новых операций; downgrade до 7bb10cf49ac2 → upgrade → check прошли | [migration-final](evidence/2026-10-16/migration-final.txt) |
| Frontend | tsc/Vite PASS; npm ci выполнен в Docker; lint 0 ошибок, 9 предупреждений set-state-in-effect | [build](evidence/2026-10-16/frontend-final.txt), [lint](evidence/2026-10-16/frontend-lint.txt) |
| Chrome 155.0.8059.84 | 8 сценариев одним итоговым прогоном PASS, включая pan/zoom/tooltip/click/390px и map loading/empty/error recovery/report progress; runtime pageerror=0 в общем сценарии | [browser-final](evidence/2026-10-16/browser-final.txt), [map](evidence/2026-10-16/browser-map.txt), [compact](evidence/2026-10-16/compact-chrome.png) |
| Clean clone | Локальный Git clone 860c15b → env example → Docker build → новые volumes → миграции → seed 20000 → smoke PASS; после обновления до 50cbdd9 — 3 Chrome flows PASS | [clean-deployment](evidence/2026-10-16/clean-deployment.txt), [browser-clean](evidence/2026-10-16/browser-clean.txt) |
| Docker / ML image | backend/migrate/frontend собраны, API/PG healthy; отдельный ML image собран | [build](evidence/2026-10-16/docker-build.txt), [ML build](evidence/2026-10-16/ml-container-build.txt) |
| Сохранённый ML-контракт | Настоящий frozen gas runtime на явно синтетической истории: 1 сохранённый результат, 2.391 с; provenance/window/idempotence/no-auto-alert/stub rejection проверены | [ML contract](evidence/2026-10-16/ml-contract-real.txt) |
| Near-real-time | telemetry → DB → уведомление: 0.244 с до сохранённого уведомления; новых прогнозов от telemetry не создаётся | [telemetry](evidence/2026-10-16/telemetry.txt) |
| TLS | 1.2/1.3 разрешены, 1.1 отвергнут; HTTPS health 200, HSTS/CSP; локальный тестовый сертификат | [TLS](evidence/2026-10-16/tls.json) |
| Backup/restore | Автозапуск/ручная копия, checksum, rotation/отказ проверены; новая БД: d01602, 200000 событий, restore 1 с; восстановленный API smoke PASS | [restore](evidence/2026-10-16/restore.txt), [smoke](evidence/2026-10-16/restored-smoke.txt), [failure/rotation](evidence/2026-10-16/backup-checks.txt), [права metadata](evidence/2026-10-16/backup-metadata.txt) |

Синтетические входные данные и mock явно обозначены. Контрактные unit tests с fixture
не являются источником прогнозов demo и не оценивают Precision/Recall.
Проверка настоящего runtime не меняет его предметную математику.

Дополнительный экспорт: 5050 явно синтетических заявок → 5000 строк с усечением.
XLSX: 0.392 с / 119074 байт; PDF: 15.064 с / 516137 байт / 295 страниц.
Кириллица и metadata проверены извлечением; визуально просмотрены первая/последняя страницы,
не все 295. [Результат](evidence/2026-10-16/reports-large.json),
[первая](evidence/2026-10-16/report-first.png), [последняя](evidence/2026-10-16/report-last.png).

## Матрица мастер-плана

Команды приведены относительно корня репозитория. Backend команды запускаются из backend
в отдельной ENVIRONMENT=test / POSTGRES_DB=ldt_test, **не в БД с демонстрационными данными**.
Ссылки Implementation указывают файлы кода; актуальный список API/миграций — [repository-audit](evidence/2026-10-16/repository-audit.json).

| Requirement | Status | Implementation | How to verify / Command/test | Actual result | Evidence | Known limitation |
|---|---|---|---|---|---|---|
| A. Свежая приёмка backend/frontend | PASS | backend/tests, frontend/e2e | compileall; alembic upgrade/check; pytest; npm ci/lint/build; playwright test | 82 backend + 8 Chrome PASS | backend-final, frontend-final, browser-final/map | Полная матрица всех UI-состояний отдельно не автоматизирована |
| A/O. Clean Docker/PG | PASS | infra/compose.yaml, Dockerfile | clone → env → compose build/up --wait → seed → smoke | Новая БД/тома; 20000 событий; smoke + 3 Chrome PASS | clean-deployment, browser-clean | Использован кеш зависимостей Docker; clone локальный, опубликованная main ещё старая |
| B. Railway demo | PARTIAL | публичный URL / read-only Railway CLI snapshot | HTTPS GET /, /health, /ready; read-only CLI services | 200/200/200; API/PG running; manager login 200, 79 объектов, read API 200, admin reads 403, logout 200 → 401 | public-demo.json, public-demo-read-account.json, railway-services.json | Manager login/read/logout/401 и 403 admin API подтверждены; остальные облачные роли/полнота данных не перепроверены; scheduler/integrations не развёрнуты постоянно; ветка не опубликована |
| C. Draft workflow | PASS | api/v1/requests.py, predictions.py, RequestReview.tsx, d01601 | test_request_drafts; real gas Chrome flow | Draft создан, отредактирован, подтверждён; история и связь сохранены | request-tests, browser-draft/final, draft-confirmed-chrome.png | Ручная обычная заявка сохраняет new; внешнее подтверждение draft запрещено |
| D. UX/loading/error/empty/success | PARTIAL | api/session.ts, SessionGate, AppErrorBoundary, страницы | Chrome normal + intercepted 503 recovery; build | Понятный error/retry, timeout, feedback, нет pageerror в основном flow | browser-final, compact-chrome.png | Не выполнен полный ручной перебор каждого состояния/темы/роли; 9 lint warnings |
| E. Карта/семантика | PASS | SchematicMap.tsx, MapPage.tsx, geo.py | test_real_geo_and_schematic_fallback; Chrome map test | Pan/zoom/tooltip/click, sensor deep link, легенда «Фактическое состояние» | browser-map, backend-final | Без исходных координат размещение условное; Point достаточно по решению владельца |
| F. Backend RBAC/auth/CSRF | PASS | core/security.py, api/v1/auth.py | test_security_acceptance, test_workflows, test_request_drafts | 401/403, роли, login/logout/expiry, CSRF проверены | backend-final.xml | Проверка локального приложения; не внешний penetration test |
| F. LDAP/AD | PARTIAL | core/ldap_adapter.py | test_ldap_contract | TLS verify/read-only/no-referrals/escaped search/no-fallback PASS | backend-final.xml | Настоящего каталога/CA/групп нет |
| G. Audit | PASS | core/middleware.py, RequestChange, d01602, admin.py | attributed_actions; password absence; request/decision/import flows | Actor/role/time/action/entity/result, history, отказ в доступе сохраняются | backend-final, security-tests | Исторические/анонимные поля nullable; БД не заменяет независимый WORM/SIEM |
| H. Imports | PASS | ingestion/csv_loader.py, tabular.py, import registry | test_import_acceptance; test_workflows formats; Chrome JSON | 4 формата, duplicate/schema/oversize/partial bad/interrupt/retry/rollback PASS | import-tests, backend-final, browser-final | Limits и формат колонок — INTEGRATIONS; произвольные новые схемы не угадываются |
| I. Mock integrations | PASS | integration_worker.py, integrations service, mock_source.py | test_integration_acceptance; compose.mock + actual worker → Chrome | 5 источников, 500/timeout/retry/cursor/upsert/idempotence; linked notification/read/audit | mock-e2e, operations, browser-import-mock/final | Только mock/adapter; не промышленное подключение |
| J. Web notifications | PASS | platform.py, Notifications.tsx | per-user visibility, stream duplicate, Chrome exact sensor/read | Хранение, индивидуальное read, дедупликация, переход работают | backend-final, browser-final | Poll 15 с после ответа; без новой эскалации/SMTP/SMS/Telegram |
| K. Reports | PASS | api/v1/reports.py | test_reports; Chrome PDF/XLSX download | Metadata, encoding, empty/large/truncation/formula protection проверены | backend-final, browser-final | Лимит 5000 строк и 367 дней; «локальные заявки», не внешние выполненные ремонты |
| L. Observability | PASS | operations.py, d01602, workers, backup metadata | test_operational_status; runtime metadata under API uid | API/DB, heartbeat, import/job, failures, backup доступны без credentials | backend-final, operations-final.json, backup-metadata | Last_seen требует контроля возраста; pool только текущего процесса, не агрегат |
| M. Performance | PASS | tests/load.py, четыре API workers | LOAD_USERS=20, LOAD_ROUNDS=3, interval=0.1 | 918 requests, 0 ошибок, показатели ниже | load.json, load-final.txt | Короткая локальная нагрузка; не endurance/целевое оборудование/SLA |
| N. Backup/restore | PARTIAL | backup.sh, restore.sh, compose volume | backup; failure; old-file rotation; restore new DB; smoke | 200000 событий восстановлены, checksum и отказ/rotation PASS | backup*, restore, restored-smoke | Полный 12-летний объём и offsite/RPO/RTO не проверены |
| P. Chrome | PASS | Playwright channel chrome | login→map→sensor/history→prediction→decision→draft→reports→logout | Основные flows и компактная навигация PASS | browser-* | Исчерпывающая визуальная матрица остаётся ручной |
| P. Яндекс.Браузер | NOT TESTED | YANDEX_BROWSER_PATH support | checklist ниже; playwright --project=yandex | В трёх стандартных путях браузер отсутствует | browser-availability.json | Chromium/Chrome не выдаётся за нативный Яндекс |
| Q. Documentation | PASS | README, ARCHITECTURE, INTEGRATIONS, SECURITY, COMPLIANCE, RUNBOOK | Проверка ссылок/кода; старые карты и отчёты помечены historical | Нынешний статус отделён от сентября и облака | docs-validation.json | Презентация/актуальный DOCX/PDF — отдельные материалы |
| R. Evidence | PASS | docs/evidence/2026-10-16 | raw logs, JUnit, metadata, screenshots | Свежие положительные и исходные отрицательные результаты сохранены | [индекс](evidence/2026-10-16/README.md) | Логи не подтверждают непроверенные промышленные claims |
| S. Submission artifacts | PARTIAL | GitHub, Railway, docs | anonymous HTTPS + файловый поиск | Repo/demo доступны 200; документация в Git | submission-links.json | Октябрьская ветка только локальна; актуальные presentation и accompanying DOCX/PDF в ветке отсутствуют |

Имена evidence без расширения в таблице относятся к одноимённым файлам каталога
[evidence/2026-10-16](evidence/2026-10-16/). Исходная инвентаризация: 35 API-операций,
12 миграций, 12 backend test modules, 9 frontend routes, 6 фактических ролей.
CI расширен, но GitHub Actions на новой ветке **NOT TESTED**: push запрещён.

## Нагрузка

Среда: локальный Docker Desktop/Linux PostgreSQL16, 4 API workers, около 200000 исходных
событий плюс записи тестов. Три профиля выполнены последовательно, без параллельного
браузерного/сборочного теста. Отдельные старые проекты на машине оставались запущены.
Baseline 18 / normal 360 / mixed 540 запросов; login/logout не входят в эти счётчики.
Mixed: чтения + POST request + PATCH in_progress + PATCH completed.

| Профиль | Requests | Errors | Error rate | p50 ms | p95 ms | p99 ms | RPS |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 user | 18 | 0 | 0 % | 25.705 | 122.656 | 122.656 | 9.668 |
| 20 users normal | 360 | 0 | 0 % | 57.576 | 284.264 | 347.404 | 138.210 |
| 20 users mixed | 540 | 0 | 0 % | 60.735 | 274.828 | 384.216 | 144.156 |

CPU/RAM сохранены двумя Docker stats снимками до/после, **не пиковым профилем**.
DB pool доступен как мгновенный показатель текущего процесса; полной временной серии нет.
Квантили на коротком baseline имеют малую статистическую устойчивость.
PASS означает отсутствие HTTP/transport ошибок; допустимый процент деградации не выдуман.

Полный разбор состояний экранов: [UI_STATE_AUDIT_2026-10](UI_STATE_AUDIT_2026-10.md).
Изменённые файлы и коммиты: [CHANGE_MANIFEST_2026-10](CHANGE_MANIFEST_2026-10.md).

## Исходные отказы и исправления

- Первый smoke выполнялся одновременно с bulk seed и получил timeout карты.
  После окончания seed smoke прошёл; изолированное чтение карты заняло 0.672 с.
- Первый Chrome login на нестандартном порту получил 403: Origin отсутствовал в тестовом
  override CORS_ORIGINS. Исправлена конфигурация теста, не ослаблена проверка Origin.
- Первый clean startup: POSTGRES_* оболочки перекрыли --env-file, пароль контейнера PG
  отличался от backend env_file. Тестовое окружение приведено к одной конфигурации.
- Backup metadata были 0600, API uid10001 не мог их читать. Исправлены только права
  безопасных меток на 0644; dump остались 0600, том API read-only. Подтверждено runtime.
- Pan-test сначала пытался тянуть карту под карточкой объекта; hover ожидал неподвижности
  анимированного SVG. Тест исправлен на открытую область и реальное движение указателя;
  поведение приложения не подменяется принудительной отправкой событий.

- Повторный mock UI-тест исчерпал старые непрочитанные уведомления при остановленном
  mock worker. Источник возобновлён; тест ждёт новое фактическое mock-событие и polling,
  после чего все восемь сценариев прошли. Тест требует работающих mock/worker;
  старое прочтение пользователя не удалялось. После приёмки генерация остановлена.

## Внешние зависимости и фиксированные исключения

**EXTERNAL DEPENDENCY:** промышленный LDAPS/CA/группы; GET URLs/credentials и реальные
поля СМВУ/ОДС/оборудования/заявок/погоды; реальная Point-геометрия;
полный обезличенный архив; offsite backup, защищённый аудит/SIEM, мониторинг,
корпоративные DNS/TLS и испытания полного восстановления.

**ML:** качество и калибровка существующей proxy-цели на подтверждённых реальных исходах
этим этапом не доказаны. Новые классы/модели/retraining/сезонность и изменение математики —
**OUT OF SCOPE (FIXED DECISION)**. То же относится к новой GIS-концепции,
свободному UI-редактору Top-K/cooldown, SMTP/SMS/Telegram и новой политике эскалации.
Предметные правила РТЭК не добавлялись без источника; существующая рекомендация ручная.

Дополнительные непроверенные пункты не скрыты под внешними зависимостями:
нативный Яндекс, полная визуальная матрица UI, актуальная презентация/сопроводительный
DOCX/PDF, остальные облачные роли/полнота данных, remote CI и публикация новой ветки.

## Точный ручной checklist перед показом

1. Выбрать явно текущую локальную версию либо опубликованное сентябрьское demo.
   Не заявлять, что локальные commits уже работают в Railway.
2. В Chrome и установленном Яндекс.Браузере: login manager → карта → zoom/pan/tooltip →
   объект → конкретный датчик → график/история; проверить условные точки и фактические цвета.
3. Manager: чтение доступно, изменяющие API запрещены. Dispatcher: прогноз → detail →
   decision → recommendation → **черновик** → правка → подтверждение new → in_progress →
   completed/cancelled. Technician не подтверждает draft.
4. Web notification → точный объект/канал → read; обновить страницу; проверить
   независимость прочтения для другой учётной записи. При потере сети показать ошибку,
   восстановить сеть и дождаться очередного опроса.
5. Импорт четырёх форматов → registry/history; duplicate и invalid файл → понятный результат.
   Отчёты PDF/XLSX: период, заголовок, источник, количество, кириллица, пустой результат.
6. Проверить empty/loading/error/success на каждом разделе, светлую/тёмную тему,
   масштаб 100/125/150 %, узкий экран, длинные названия. Logout → закрытый API 401.
7. Admin: operations last_seen/last_success/import/job/backup, audit actor/role/result.
   Для промышленного запуска отдельно выполнить AD, реальные источники и offsite restore.
8. Яндекс: задать YANDEX_BROWSER_PATH и выполнить `npx playwright test --project=yandex`
   на изолированном стенде; записать версию и результат. Пока это NOT TESTED.
9. Собрать актуальную презентацию и сопровождающий DOCX/PDF, открыть ссылки без
   авторизации. Обновить облако/публиковать Git только после отдельного разрешения владельца.
