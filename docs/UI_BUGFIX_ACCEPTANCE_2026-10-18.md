# Приёмка точечных UI-исправлений — 18.10.2026

Ветка `release/final-rc`, исходный HEAD `9b8cb86`, чистое рабочее дерево перед началом.
Application/UI HEAD `8c39deb`; следующий documentation commit не меняет приложение.
Итоговые локальный/remote HEAD указаны в отчёте выполнения и проверяются Git.
Main не менялся. Каждый завершённый блок отправлен обычным push в origin/release/final-rc.
Новый общий hardening, load, backup/restore, migrations и deployment не выполнялись.

Среда: Windows 11 Home 10.0.26200, Chrome155.0.8059.84, Playwright channel=chrome.
Frontend из текущих исходников через локальный Vite, реальный QA API/PostgreSQL из RC.
Все изменяющие проверки выполнялись на изолированном QA, не на публичном demo.

## Проблемы, причины и результат

| Проблема пользователя | Воспроизведение / root cause | Исправление / проверка |
|---|---|---|
| Заполненная заявка не создаётся | Для manager воспроизведён disabled без объяснения: canWrite исключает просмотр. Пустой объект/пробельная тема также блокировали молча. У dispatcher не воспроизведён отказ корректной полностью заполненной формы | Явные причины рядом с кнопкой и ошибки внутри формы; required для объекта/темы, guard повторного submit; права сохранены. POST200, корректный payload, история и audit PASS |
| Подтверждение draft | У роли без права review fieldset был отключён без объяснения; пробельная тема также не объяснялась | Причина вне disabled fieldset. Все поля→PATCH с expected_updated_at→new200; history draft→new; backend audit PASS |
| Тревоги/импорт нечитаемы в dark | Прозрачное белое glass-покрытие над сложным фоном, серый мелкий текст; rows10/12px | Общие непрозрачные panel/header/control surfaces для Alerts/Imports/Journal/Objects, согласованные foreground/border/hover/badges |
| Мелкая типографика | Много локальных 7–13px правил перебивали body font | Общие tokens: body16px, rows15px, controls15px, metadata13px, вложенный текст таблиц14px. Настройка масштаба не добавлялась |
| Карта съезжает при resize | map height100vh плюс notifications42px: низ карты842px при viewport800 | Workspace распределяет оставшуюся высоту через flex; container queries по реальной ширине; bounds/no global overflow на1024/1152/1280/1440/1920 PASS |
| Pinch скрывает интерфейс | React wheel listener passive: synthetic ctrl-wheel defaultPrevented=false; браузер мог масштабировать страницу. Фиксированный шаг не учитывал high-frequency/deltaMode | Native passive:false, preventDefault, нормализация pixel/line/page/ctrl/meta, bounded exponential delta и синхронный view ref. 240 wheel events, NaN/Infinity guards, zoom1..4, normal wheel и +/-/reset PASS |
| Object panel при zoom | Drawer уже находился вне SVG; проблема связана с page zoom и высотой workspace | Размер drawer не зависит от map zoom; clamp по viewport, sticky close, внутренний scroll, sensor panel оставляет место controls. Bounds/close/large zoom PASS |
| Прозрачные filters / невидимые кнопки журнала | Glass !important поверх контента; несогласованные текст/фон, отдельные тёмные sort icons | Opaque popover/input/select/button, semantic foreground/focus/disabled, читаемый Apply и sort; обе темы PASS |
| Плоский Prediction и light contrast | Не было content layers; status-notice имел постоянный тёмный фон, а текст следовал светлой теме | Cards: сводка, контекст, рекомендация, решение, история; общий themed control layer. Контраст notice/body/metadata≥4.5; текущий proxy value сохранён |
| Settings смещается при открытии панели | Notifications раскрывались в потоке и меняли доступное место. Отдельного right drawer в Settings нет; изолированный горизонтальный сдвиг, описанный пользователем, отдельно не воспроизведён | Notifications раскрываются overlay при стабильной высоте bar; max-width520, центрирование main. Автотест X/Y до/после PASS |
| Логотип похож на кнопку / alignment | Градиентная плашка/тень у неинтерактивного div; несогласованные отступы header/nav | Без button-like background/hover, cursor default; общая сетка24px; logo и arrow имеют общую ось |
| Стрелка sidebar / divider | Button и nav links использовали отличающееся выравнивание, footer без отдельного spacing | Grid icon centering, collapsed/expanded проверки, aria-expanded/controls, padding16px после divider |

В текущем request API нет скрытых обязательных полей date/time, responsible person/unit
или request type. Обязательны object_id и title; channel/description необязательны,
priority — существующий enum. Поля/бизнес-правила не придумывались, RBAC не расширялся.
UI regression проверяет object1/channel1/title/description/high в фактическом POST.
Отдельный обычный QA draft проверяет полную review-форму; это не новый ML-прогноз.
Backend test дополнительно проверяет prediction/recommendation→draft→new с прежним
явно тестовым контрактным fixture в отдельной disposable DB.

## Проверки

| Проверка / команда | Фактический результат | Evidence |
|---|---|---|
| npm run build (tsc -b + Vite) | PASS | [final-build](evidence/ui-fixes-2026-10-18/final-build.txt) |
| npm run lint | 0 ошибок, 10 прежних set-state-in-effect warnings | [final-lint](evidence/ui-fixes-2026-10-18/final-lint.txt) |
| pytest tests/test_request_drafts.py tests/test_request_concurrency.py tests/test_security_acceptance.py | 21PASS, 2 dependency warnings,23.51с | [request-backend](evidence/ui-fixes-2026-10-18/request-backend.txt) |
| Filled form/review Chrome | 3PASS,11.9с | [request-chrome](evidence/ui-fixes-2026-10-18/request-chrome-final.txt) |
| Lists/filters/import/validation Chrome | 4PASS,12.3с | [readability-chrome](evidence/ui-fixes-2026-10-18/readability-chrome.txt) |
| Map resize/pinch/normal wheel/controls/history Chrome | 4PASS,12.7с | [map-chrome](evidence/ui-fixes-2026-10-18/map-chrome.txt) |
| Основной npx playwright test --project=chrome | 18PASS,1skip,1.0мин; pageerror/overflow assertions в затронутых тестах | [final-chrome](evidence/ui-fixes-2026-10-18/final-chrome.txt) |
| После последнего выравнивания logo/grid и контраста Close | 3PASS,37.1с, включая повтор визуальной матрицы; повторные build/lint PASS | [final-layout](evidence/ui-fixes-2026-10-18/final-layout-chrome.txt) |
| Визуальная матрица | 37PNG: обе темы1280×800/1440×900, drawer1024×700/1920×1080, sidebar states, draft | [matrix](evidence/ui-fixes-2026-10-18/screenshots/matrix.json) |
| ML freeze | Runtime/bundles/scheduler paths без diff относительно9b8cb86 | [ml-unchanged](evidence/ui-fixes-2026-10-18/ml-unchanged.txt) |
| Git hygiene | Известные token/private-key signatures, QA password, env/trace paths не найдены в staged text | [repository-check](evidence/ui-fixes-2026-10-18/repository-check.json) |

Один skip — прежний opt-in RC visual matrix; новая visual matrix данного прохода выполнена.
Первый общий запуск выявил зависимость старого polling fixture от второго initial
запроса в React StrictMode. Тест теперь задерживает первый poll после появления
notice; повтор подтвердил read race/failure/recovery. Product polling не переписывался.

Сохранённый настоящий prediction использован только для UI/read/decision/link tests:
новый inference не запускался, модель/score/thresholds/shadow/abstain не менялись.
RUN_ML_E2E включает существующий UI flow по сохранённому результату, не расчёт модели.
QA fixture role=manager подменяет только auth/me для проверки текста блокировки UI;
настоящие ограничения сервера проверены отдельными PostgreSQL RBAC tests.

## Снимки

Все 37PNG сохранены вместе с матрицей. Для каждого route снимки доступны в dark/light
на1280/1440; ниже ссылки на просмотренные представители требуемых экранов.

| Экран | Dark | Light |
|---|---|---|
| Alerts | [1440](evidence/ui-fixes-2026-10-18/screenshots/dark-1440-alarms.png) | [1280](evidence/ui-fixes-2026-10-18/screenshots/light-1280-alarms.png) |
| Imports | [1440](evidence/ui-fixes-2026-10-18/screenshots/dark-1440-imports.png) | [1280](evidence/ui-fixes-2026-10-18/screenshots/light-1280-imports.png) |
| Journal/filter | [1280](evidence/ui-fixes-2026-10-18/screenshots/dark-1280-journal.png) | [1280](evidence/ui-fixes-2026-10-18/screenshots/light-1280-journal.png) |
| Predictions | [summary](evidence/ui-fixes-2026-10-18/screenshots/dark-1280-predictions.png), [decision](evidence/ui-fixes-2026-10-18/screenshots/dark-1280-prediction-decision.png) | [summary](evidence/ui-fixes-2026-10-18/screenshots/light-1280-predictions.png), [decision](evidence/ui-fixes-2026-10-18/screenshots/light-1280-prediction-decision.png) |
| Settings | [1280](evidence/ui-fixes-2026-10-18/screenshots/dark-1280-settings.png) | [1280](evidence/ui-fixes-2026-10-18/screenshots/light-1280-settings.png) |
| Map | [1440](evidence/ui-fixes-2026-10-18/screenshots/dark-1440-map.png) | [1280](evidence/ui-fixes-2026-10-18/screenshots/light-1280-map.png) |
| Request create | [1280](evidence/ui-fixes-2026-10-18/screenshots/dark-1280-request.png) | [1280](evidence/ui-fixes-2026-10-18/screenshots/light-1280-request.png) |

[Reduced drawer1024](evidence/ui-fixes-2026-10-18/screenshots/reduced-1024-map-drawer.png),
[wide drawer1920](evidence/ui-fixes-2026-10-18/screenshots/wide-1920-map-drawer.png),
[expanded sidebar](evidence/ui-fixes-2026-10-18/screenshots/sidebar-expanded.png),
[collapsed sidebar](evidence/ui-fixes-2026-10-18/screenshots/sidebar-collapsed.png),
[filled draft](evidence/ui-fixes-2026-10-18/screenshots/draft-filled.png).
Избранные снимки просмотрены визуально; все37 сняты автоматически. Overflow проверен
для28 route/theme/viewport сочетаний, bounds карты — отдельно. Это не попиксельная
проверка каждой строки каждого экрана.

## Публикация и границы проверки

| Commit | Блок | Push |
|---|---|---|
| 726fdff | Валидация/объяснение блокировки и filled request/draft regression | PASS origin/release/final-rc |
| 4eb648b | Typography, shared opaque surfaces и читаемый журнал | PASS origin/release/final-rc |
| 8f60b81 | Map resize, непассивный нормализованный wheel/pinch, bounds | PASS origin/release/final-rc |
| 8c39deb | Prediction cards, settings/sidebar, final Chrome/visual evidence | PASS origin/release/final-rc |

Документационный commit этого отчёта также публикуется обычным push после проверки ссылок.
Список изменённых файлов: [changed-files](evidence/ui-fixes-2026-10-18/changed-files.txt).

- **NOT TESTED:** физический тачпад на машине пользователя. Synthetic ctrl/meta wheel,
  delta modes, burst, normal wheel, +/- и пределы zoom проверены в Chrome;
  это не заменяет ручной pinch реальным устройством.
- **NOT TESTED:** нативный Яндекс.Браузер и OS/browser zoom125/150% в этом проходе.
- **NOT DEPLOYED:** публичный Railway demo не обновлялся. Push ветки не является
  публикацией нового стенда; ручную проверку пользователя нужно повторить на RC после
  отдельно разрешённого deployment. Main/production secrets не менялись.
- Тяжёлые backend/load/backup/infra проверки не повторялись: runtime backend,
  миграции и инфраструктура этим проходом не изменены. Добавлен один backend regression test.
- Уполномоченному dispatcher полностью заполненная форма успешно отправляется;
  исходный отказ при таких условиях не воспроизведён. Если он повторится на новом RC,
  нужны роль, точный экран/действие и HTTP status; расширять RBAC ради обхода нельзя.

Локальный Docker первоначально не стартовал из-за stale IPC socket Windows.
Перенос/удаление socket не удались; запуск восстановил владелец среды.
Factory Reset, удаление БД/volumes/секретов не выполнялись. Это не исправление проекта.
