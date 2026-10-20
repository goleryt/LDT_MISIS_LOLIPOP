# Browser acceptance — release/final-rc

19.10.2026: [native Chrome remote PASS](REMOTE_RC_ACCEPTANCE_2026-10-19.md),
14 recorded checks, 21 screenshots, public Railway, application `ee16251`.
Report-only correction `d4f3e09`: Moscow midnight regression and remote PDF/XLSX PASS;
one additional report screenshot (22 total), local Chrome16 PASS / 4 opt-in skips.
Yandex executable/App Paths checked again: **NOT TESTED — MANUAL ACTION REQUIRED**.
Physical touchpad: **MANUAL TOUCHPAD VERIFICATION REQUIRED**, synthetic remote pinch PASS.
For manual checks use the live demo and record the current admin operations commit;
do not run fixture seed scripts, hardcoded object-ID tests or inference against Railway.

16.10.2026, Windows 11 Home 10.0.26200. Chrome 155.0.8059.84 проверен нативно
через Playwright channel=chrome. Размеры: 1280×800, 1440×900, 1920×1080;
тёмная/светлая темы. Мобильная версия не является целью RC.

Яндекс.Браузер: **NOT TESTED**. Исполняемый файл не найден в стандартных путях
пользователя/Program Files и в трёх App Paths registry locations.
Chrome не выдаётся за нативную проверку Яндекса.

## Повтор нативного smoke

На отдельном QA задать BASE_URL, TEST_USERNAME, TEST_PASSWORD в окружении.
Установленный Яндекс подключается через YANDEX_BROWSER_PATH, затем из frontend:

```powershell
npx playwright test --project=yandex
```

Для уже сохранённого настоящего прогноза RUN_ML_E2E=true включает существующий UI
flow; модель не запускается этим флагом. RUN_MOCK_E2E=true требует работающих mock
источника/worker. RUN_RC_VISUAL=true включает desktop screenshots, RC_VISUAL_DIR —
отдельный каталог. Пароли/cookies/traces не коммитить. ALLOW_SELF_SIGNED_TLS=true
действует только для loopback URL тестового TLS; для публичного HTTPS не применять.

## Ручной checklist и запись результата

Зафиксировать OS, browser version, дату, URL, application commit и роль.
Для каждого пункта записать PASS/FAIL/NOT TESTED и ссылку на evidence:

- Login → карта; marker/tooltip/zoom/pan/reset; выбранный объект и условная геометрия.
- Object → sensor → график/history; alarm и notification ведут к конкретному sensor.
- Deep link, refresh, Back/Forward; прогноз открывается/закрывается через URL.
- Prediction → decision → recommendation → editable draft → отдельное confirmation.
- Manager read-only; technician обычная заявка; dispatcher draft; admin audit/operations.
  Logout → другая роль; прямые REST 401/403/CSRF/expired session.
- CSV/XLSX/JSON/XML → registry; duplicate/invalid/oversized → понятный feedback.
- Reports PDF/XLSX: заголовок, период, кириллица, timezone, row count, empty/truncated.
- Notifications: personal read/persistence, старый polling не возвращает прочитанное,
  потеря связи/восстановление; длинный текст не выталкивает элементы.
- Desktop 1280/1440/1920: sidebar, таблицы, drawer, sensor/chart, prediction detail,
  длинные названия, error banners, поля/календарь отчёта, доступность кнопок и прокрутки.

Административной web-страницы нет: CLI и защищённые API проверяются отдельно.
Внешняя проверка corporate AD и браузерных политик заказчика не заменяется этим smoke.

RC: 11 Chrome PASS +3 повторных visual/navigation +4 HTTPS flows.
Избранные просмотренные снимки и автоматические 30 измерений находятся в
[evidence/release-rc/visual](evidence/release-rc/visual/matrix.json).
Это не полный перебор каждого loading/empty/error/success на каждой роли.
