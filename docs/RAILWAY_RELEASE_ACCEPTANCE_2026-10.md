# Публичное обновление Railway — план и фактическая приёмка

## Обновление командного UI — 20.10.2026

**PASS в проверенном демонстрационном объёме.** Функциональный release `18af8fa339c8da54db5337fb6592cb0a87a0dcad`,
ветка `release/final-rc`, [CI39408268560](https://github.com/goleryt/LDT_MISIS_LOLIPOP/actions/runs/39408268560) — все4 jobs, attempt1.
Предыдущий runtime5f27421 / deployment8006b5a4-ae40-442b-8c23-5b122ad4b91a;
новый deployment **b1bd6fee-0e94-46b9-8d76-11b555c8e06f**, SUCCESS. Версия приложения0.2.0.

Использованы прежние project/environment/web/PostgreSQL и volume. Источник deployment:
точный tracked Git archive из release/final-rc, CLI upload; автоматическая GitHub branch
metadata у этого способа отсутствует. APP_COMMIT, source archive SHA и фактические JS/CSS
подтверждены [identity](evidence/visual-integration-2026-10-20/remote-build-identity.json), [deployment](evidence/visual-integration-2026-10-20/deployment.json).
Текущий documentation-only tip проверяется отдельно после публикации; код runtime должен
побайтно совпадать с этой функциональной версией, final tag и merge main не создаются.

| Проверка | Статус | Фактическое доказательство |
|---|---|---|
| Gate до rollout | PASS | Backend151, Chrome33/8 optional skips; новый Docker/clean startup; local visual matrix; [local](evidence/visual-integration-2026-10-20/local-gate.json) |
| Concurrent imports | PASS | 8 изолированных кейсов,5/10/20 разных авторизованных пользователей; CSV/XLSX1000/25000 строк;1962 обычных API /0 ошибок; [дополнение](IMPORT_VISUAL_SUPPLEMENT_2026-10-20.md) |
| Backup | PASS | PG18 dump10095982 bytes, SHA256 `73a3fc634d33cb5bc15a71db63a199cc029b520928fb973efcf14ada3336e5fd`; копия вне Git и исходного контейнера |
| Restore / compatibility | PASS | Новая отдельная DB,173867 событий, schema check/API/login; [restore](evidence/visual-integration-2026-10-20/backup-restore.json). Не RTO полного архива |
| Migration | PASS | d01901→d01901, upgrade head без новых миграций; фактический `alembic current`: d01901(head). Никаких downgrade/drop/очисток |
| HTTPS / routing | PASS | TLSv1.3, проверены цепочка и hostname; HTTP301→HTTPS; root/health/ready200. SPA refresh/deep links работают |
| Auth / RBAC | PASS в smoke scope | admin/dispatcher/manager/technician/analyst: login/read, wrong-role403, CSRF403, Secure/HttpOnly/SameSite cookies, logout→401; [API](evidence/visual-integration-2026-10-20/remote-api.json) |
| Remote user flows | PASS с отдельной оговоркой уведомлений | Map/object/sensor/history, fast Back×3, alarm, manual request, import+duplicate, PDF/XLSX, themes/sidebar;14 PASS и1 NOT TESTED; [browser](evidence/visual-integration-2026-10-20/remote-browser.json) |
| Scenario workflow | PASS | Сохранённый SF forecast2→новый draft request12→редактирование→new; audit/history/idempotency. Fire request9 проверен повторно, новый Fire draft не создавался; [scenarios](evidence/visual-integration-2026-10-20/remote-scenarios.json), [audit](evidence/visual-integration-2026-10-20/remote-request-audit.json) |
| Visual QA | PASS в desktop scope | Remote136 кадров, обе темы1024×768/1280×800/1440×900/1920×1080,0 page errors; формы/ошибочный период ещё4 сочетания; [matrix](evidence/visual-integration-2026-10-20/visual-remote.json), [forms](evidence/visual-integration-2026-10-20/remote-forms.json) |
| Export | PASS в проверенном периоде | PDF открывается, кириллица извлекается; XLSX читается итерацией строк, без предположения о worksheet dimensions; [exports](evidence/visual-integration-2026-10-20/remote-report-validation.json) |
| Default source data | PASS | Исходный журнал169993 строк сохранён. Всего173868 событий после одного помеченного нормального JSON demo observation;97 объектов/11490 каналов |
| ML invariance | PASS технической интеграции | 1 gas run/3 scores/3 predictions;1 scenario run/2 SF+1 Fire. Gas records SHA `aee92bc6…a127d`, immutable scenario SHA `3320a2be…8993d` совпали до/после. Нового public inference не было |
| Notifications | PARTIAL | На публичном dispatcher нет unread; переход к сущности NOT TESTED. На восстановленной локальной копии переход по существующей фактической тревоге и read PASS; [local flow](evidence/visual-integration-2026-10-20/restored-data-flow.json) |

### Экспериментальные контуры и эксплуатационные ограничения

SCENARIO_ENABLED / ALLOW_PRODUCTION / SENSOR / FIRE=true сохранены; остальные головы
выключены. operational_ready=false, automated_action_allowed=false. Gas остаётся
shadow/proxy, SF/Fire — E4 synthetic scenario_score. Не вероятность реальной аварии,
не подтверждённые инциденты. Модельные файлы, зависимости, thresholds/calibration,
feature engineering и scheduler semantics не изменены.

CI1bdb8f2 дважды остановился ДО inference на ECR HTTP429. Исправление18af8fa меняет
только registry override в CI: официальный Python3.12 image **того же OCI SHA256** через
Docker Hub. Frozen numeric parity в read-only/network-none runtime PASS; [proof](evidence/visual-integration-2026-10-20/ci-registry-resolution.json),
[acceptance](evidence/visual-integration-2026-10-20/same-base-runtime-acceptance.json). Полезные tests не отключались.

Web memory.max999997440 bytes (~953.67 MiB), CPU2 vCPU. QA limit1 GiB/2 vCPU;
это разные среды, результаты локального load не выдаются за public benchmark.
Persistent integration worker и gas scheduler — not_observed; scenario worker —
completed19.10, последний конечный batch не перезапускался. Automatic backup service —
not_configured. Ручная safety copy есть; непрерывная промышленная эксплуатация не заявляется.
Новые платные ресурсы, тариф и production secrets не менялись.

### Откат приложения

Предыдущий стабильный5f274217cc566ee34b1eac26017041966452643e остаётся в истории и
совместим с d01901: baseline image/ready/API проверены на отдельной восстановленной DB.
Для возврата создать новый `git archive` этого SHA, выставить только APP_COMMIT этого
же SHA через `railway variables set --skip-deploys` для прежнего web/environment и
загрузить архив через прежний `railway up --path-as-root --service ... --environment ... --project ...`.
Project/web/environment IDs перечислены в deployment evidence. Это обычный новый application
rollout; БД, volume, новые заявки и события сохраняются. Не восстанавливать dump поверх
действующей DB и не выполнять downgrade. Отдельное восстановление допустимо только в НОВУЮ DB.
При необходимости можно отключить master experimental flag без удаления ledger/history;
в текущем обновлении flags не менялись.

Native Yandex, физический touchpad и native Chrome Zoom125/150% остаются ручными
проверками. Viewport/DPR и synthetic WheelEvent не подменяют такие результаты.

## Исторические результаты до этого обновления

Предыдущие разделы сохраняются как датированная история. Текущее состояние описано выше.

Дата 19–20.10.2026, ветка release/final-rc. План ниже сохранён для проверки
последовательности; фактические результаты и ограничения перечислены отдельно.

## План до первого изменения публичного приложения

- Исходный deployed14aad86414826c59857cbc2766d10f48a0b43ba4,
  deployment0a95e97d-c487-4358-9792-6a6422fae4b8.
- Целевой функциональный RC edb9a15eb0598bd9e321797baa15f3cb84e57da3;
  фактический CI39275844011: backend/frontend/containers/combined-runtime PASS.
- Существующие project d4c500cc-fab0-4f7f-ad7e-a52db7a5585c, production,
  web40ca29d5-bf32-4a43-bcd9-c03d05b27b9f, PostgreSQL18
  7eee6a09-108b-4ea6-ad4a-efe3b5fc93ef с volume /var/lib/postgresql/data.
  Не создавать платные сервисы, не менять тариф/секреты/volume.
- Deploy source — CLI upload, не main/GitHub auto-deploy. Точный tracked git archive
  и соответствующий APP_COMMIT, Dockerfile.cloud; migration pre-deploy upgrade head,
  readiness /ready, прежний домен и single-origin routing.
- Миграция d01602→d01901 добавляет только scenario_runs/scenario_forecasts/индексы,
  не меняет и не очищает старые таблицы. Backup PG18 скачать вне контейнера/Git,
  проверить SHA256 и restore в отдельный НОВЫЙ локальный PostgreSQL18.
- До публикации: новый build на восстановленной копии, upgrade/check, health/ready,
  source data counts, старый API, scenario master OFF. Никаких pytest fixtures
  против рабочей БД и никаких seed в восстановленную копию.
- Особенность rollback: старый код ожидает строго d01602 в /ready. Простой возврат
  старого image после миграции НЕ готовый откат. Подготовить archive14aad86 плюс
  неизменный migration script d01901: старое приложение/математика остаются,
  schema discovery принимает текущую revision. Проверить этот совместимый artifact
  на новой схеме. Обозначать его14aad86-schema-d01901, не выдавать за чистый Git SHA.
- StageA: SCENARIO_ENABLED=false; APP_COMMIT точного archive; безопасный rollout,
  migrations→web/frontend→health/ready→полный HTTPS smoke/RBAC/данные/отчёты.
- StageB: только послеA и подтверждения ресурсов/данных. Отдельный Python3.12 runtime,
  явный production guard, экспериментальные метки, никаких auto requests/alerts.
  Не сертифицировать неизвестную историю. При недостатке ресурсов/истории оставить
  master OFF и результат PARTIAL, сохранив новую работоспособную web-версию.
- Stop criteria: backup/restore/rollback не подтверждён; migration failure;
  health/ready failure; потеря старых данных; auth/RBAC/high regression; OOM.
- Rollback приложения: выключить экспериментальные flags, загрузить проверенный
  совместимый rollback archive с прежней web-конфигурацией. БД d01901 сохранить,
  не downgrade/drop. Восстановление backup допустимо только в НОВУЮ БД как отдельная
  процедура, исходная БД и её новые пользовательские записи не уничтожаются.

## Исходные факты

`evidence/railway-release-2026-10/before.json`, `database-before.json`:
96объектов,11488каналов,173864события,4заявки,3прогноза,1gas run,5пользователей,
5импортов. Web около279MB RAM при лимите1024MB/2vCPU. Persistent worker/scheduler/
automatic backup отсутствуют; старый ml-demo-job остановлен. Их running status
не выдумывается. Использование и доступные лимиты проверяются без изменения тарифа.

## Результаты

| Проверка | Статус | Фактический результат / evidence |
|---|---|---|
| Safety backup / restore | PASS | PG18 dump 9 990 957 bytes, SHA c8da06d…7205, скачан вне Git; restore в НОВУЮ local PG18 БД, upgrade d01602→d01901/check/API/login PASS; [backup](evidence/railway-release-2026-10/backup.json), [QA](evidence/railway-release-2026-10/restored-qa.json) |
| Совместимый rollback | PASS | Старое приложение14aad86 + неизменный migration discovery d01901; ready/login/gas API проверены на новой схеме. APP_COMMIT=unknown, derived artifact не выдаётся за исходный Git SHA; [artifact](evidence/railway-release-2026-10/rollback-artifact.json) |
| Stage A, master OFF | PASS | edb9a15, deployment 8a78168d-6636-4563-a975-5677be46f68b; публичный HTTPS/root/health/ready, Chrome flows, роли, заявки, безопасный demo import, PDF/XLSX; [runtime](evidence/railway-release-2026-10/stage-a.json), [browser](evidence/railway-release-2026-10/stage-a-browser.json) |
| Stage B, явный demo opt-in | PASS | ae43e33, web deployment 4c8a1b24-a013-4d11-90fe-5535a65e321e; SCENARIO_ENABLED/ALLOW_PRODUCTION/SENSOR/FIRE=true, остальные головы false; operational_ready/automated_action_allowed=false; [runtime](evidence/railway-release-2026-10/stage-b.json) |
| Отдельный batch runtime | PASS | Python3.12, существующий остановленный ml-demo-job использован как конечный batch. Deployment5e8e92ce-20fd-4424-8075-7b0cf85eb08b завершил настоящий SF/Fire inference; 3848dc43-2524-47ab-a423-5e3a238889ec повторно использовал run1 без новых результатов. Оба нормально остановлены; [first](evidence/railway-release-2026-10/job-5e8e92ce.json), [reuse](evidence/railway-release-2026-10/job-3848dc43.json) |
| Область синтетики / ML | PASS технического контракта | 810 поставленных synthetic raw rows только в scenario snapshot, не events_journal; 2 SF + 1 Fire. Реальные низкие scores 0.002341049925894857 / 0.002992514760574736, не вероятность реальной аварии. Gas score payload SHA c6586aae…54c1 сохранён; [inference](evidence/railway-release-2026-10/public-inference.json) |
| Новые публичные cards / flow | PASS | Chrome155, light/dark, 1024/1280/1440, реальный скролл Imports; отдельные review→draft→new SF/Fire, history/idempotency; 0 page errors; [browser](evidence/railway-release-2026-10/stage-b-browser.json), [screenshots](evidence/railway-release-2026-10/ui/) |
| Auth / RBAC | PASS | Пять реальных demo ролей; anonymous401, Secure/HttpOnly/SameSite cookie, CSRF403, admin operations200 только admin и403 остальным; logout→401; [roles](evidence/railway-release-2026-10/auth-rbac-timings.json) |
| Уведомления | PARTIAL | У technician/analyst read persists/idempotent PASS. Dispatcher/manager не имели unread: переход к сущности в текущем состоянии NOT TESTED; данные ради PASS не создавались |
| PDF/XLSX | PASS в проверенном объёме | Реальные выгрузки открываются, кириллица PDF проверена; count XLSX не выводится из отсутствующего worksheet dimension; [reports](evidence/railway-release-2026-10/reports.json) |
| Backup после batch | PASS | SHA0eac41ba…fc61, 10 033 861 bytes, persistent PG-volume + downloaded workstation copy. Restore в другую НОВУЮ PG18 БД, 173865events / 3 gas / 3 scenario forecasts, ready/login/API PASS; [post backup](evidence/railway-release-2026-10/post-backup.json) |
| CI предыдущих public fixes | PASS | 8cf4573 run39280306517 и ae43e33 run39280532451: все4jobs success; [CI](evidence/railway-release-2026-10/ci-prior.json) |
| Admission/load gate перед следующим rollout | PASS локально | [Отдельная приёмка](IMPORT_LOAD_ACCEPTANCE_2026-10-20.md): 5/10/20, same/different CSV/XLSX, mixed; 2871 обычных API/0errors; cancelled SQL/SIGKILL/rollback/retry; 151 backend / 30 Chrome PASS. Railway stress не проводился |
| Fresh safety backup перед import fix | PASS | SHA19aacf13…5671, 10 065 652 bytes, persistent PG-volume и скачанная независимая копия; схема d01901 не меняется; [backup](evidence/railway-release-2026-10/pre-import-backup.json) |
| Persistent integrations / scheduler | NOT TESTED | Не развёрнуты; operations показывает not_observed. Конечный scenario batch не является постоянным scheduler |
| Автоматический offsite backup | EXTERNAL DEPENDENCY | Ручные проверенные копии есть, автоматический сервис отсутствует, operations not_configured. Нужны место хранения/расписание/операторская конфигурация |
| Native Yandex / physical touchpad | NOT TESTED | MANUAL ACTION REQUIRED; Chrome synthetic pinch проверен, физического устройства/браузера в среде нет |

Ресурсы: [измерения работающего web/PG](evidence/railway-release-2026-10/resources.json).
Нулевые metrics остановленного batch **не** доказывают нулевой расход RAM во время
inference; локальный тот же runtime имел peak около216 MiB. Полная промышленная
нагрузка/12-летний архив и качество реальных аварий не проверялись.

Первый job deployment7b053ee4 не дошёл до build/БД из-за старого явного dockerfilePath
сервиса. Исправлена только существующая service configuration на ml_combined/Dockerfile;
новый сервис/тариф/secret не создавался. Две гонки browser probe исправлены ожиданием
стабильного UI и адресацией статуса по request ID, не ослаблением проверки продукта.

После нового требования об импорте дальнейший rollout был остановлен до load gate PASS.
Функциональный import fix **237ff93d01fdcbfae7b58538946d0f02c267a369** опубликован
только после 12 финальных CPU cases, rollback/fault/regression tests и фактического
[CI39338321060 PASS](https://github.com/goleryt/LDT_MISIS_LOLIPOP/actions/runs/39338321060)
со всеми4jobs. [CI evidence](evidence/railway-release-2026-10/import-fix-ci.json).

Deployment **e932826d-91ef-4ee1-acf8-6f148a53ceb7 SUCCESS**. Загрузился точный tracked
git archive237ff93, его SHA и known nonsecret import settings сохранены в
[rollout source](evidence/railway-release-2026-10/import-rollout-source.json).
Схема осталась d01901; новая миграция не добавлялась. Секреты/тариф/volume/main
не менялись; старые данные не очищались. Байты установленного limits.py совпали
с соответствующим Git blob, а не только с переданным APP_COMMIT.

[Public API acceptance](evidence/railway-release-2026-10/import-public.json):
root/health/ready200, HTTP→HTTPS redirect, сертификат проверен, пять ролей,
Secure/HttpOnly cookie, CSRF403, admin200/остальные403, logout→401.
Последовательно: dispatcher CSV1row → inserted1; тот же файл → already_imported;
admin XLSX с той же строкой → inserted0/skipped1. Реестр7/8. Это обычный smoke,
**не** concurrent/stress тест Railway. Прямой import запрещён manager/technician/
analyst с403. Максимум обработки2, Retry-After3, бюджет240s, XLSX64MiB подтверждены
в runtime. Gas mathematical output/полная запись ml_scores не изменились;
ml_runs1/ml_scores3/predictions3/scenario_runs1/forecasts3. Никакого нового inference.

Последующие documentation/evidence-only commits могут изменить APP_COMMIT без
изменения исполняемых исходников: при финальном upload проверяются CI, tracked
archive, точный runtime SHA и прежний SHA limits.py; новый stress на Railway не нужен.
Точный заключительный deployment receipt выводится отдельно от исторических stage
снимков, чтобы не создавать циклическую запись собственного commit hash в Git.

После import rollout выполнены обе настоящие Chrome browser проверки повторно:
[основной flow](evidence/railway-release-2026-10/import-browser.json),
[SF/Fire + Imports scroll](evidence/railway-release-2026-10/import-scenarios-browser.json).
Login/map/object/sensor/history, alarm→sensor, resize/wheel/synthetic pinch/large
zoom/drawer, заполненная ручная заявка, linked prediction request, JSON demo import
и duplicate registry, PDF/XLSX, themes/settings/sidebar, logout/другая роль — PASS.
SF/Fire: сохранённая ручная проверка, ссылки на отдельные ранее подтверждённые
заявки/history/idempotency — PASS; новый inference или повторное создание этих
заявок не выполнялись. Обе темы и 1024/1280/1440, настоящий user-wheel по Imports.
Непрочитанных уведомлений у dispatcher нет: linked notification navigation остаётся
NOT TESTED. Page errors и неожиданные server errors отсутствуют.
Выбранные снимки опубликованы в [ui](evidence/railway-release-2026-10/ui/),
соответствие оригинальным приватным outputs описано в
[curation](evidence/railway-release-2026-10/curated-ui.json). Трассы/credentials не публикуются.
