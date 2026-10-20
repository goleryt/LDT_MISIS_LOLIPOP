# Evidence — 16.10.2026

Актуальная интерпретация и границы: [приёмка](../../FINAL_ACCEPTANCE_2026-10.md).
Все тесты проводились локально в отдельных БД; облако читалось без изменения.

- repository-audit.json — исходная ветка/main, миграции, API, UI, сервисы, тесты.
- baseline-* — начальный прогон, 50 тестов; не итог нынешних изменений.
- backend-final.txt/xml — итоговые 82 теста; backend-tests.txt/xml — предшествующие 80.
- migration-final.txt — чистые миграции, current/heads/check, downgrade/upgrade.
- frontend-final.txt — TypeScript/Vite; frontend-lint.txt — существующие предупреждения.
- docker-build.txt, ml-container-build.txt — сборки; clean-deployment.txt — новый clone/volumes.
- browser-final.txt — 8 Chrome flows; browser-map.txt — pan/zoom/tooltip/click/390px;
  browser-clean.txt — три flow на обновлённом чистом развёртывании.
- browser-draft.txt — первый свежий draft с редактированием и подтверждением;
  повтор browser-final также проверил существующую идемпотентную связь.
- draft-confirmed-chrome.png, compact-chrome.png — просмотренные снимки интерфейса.
- import/security/request-tests.txt — целевые промежуточные проверки.
- mock-e2e.txt — агрегаты пяти mock источников и история статусов от integrator.
- operations.json — ранний снимок, до исправления прав backup-меток;
  operations-final.json — актуальная служебная выборка app.operations под API uid.
- telemetry.txt — измерение фактической телеметрии без ML.
- ml-contract-real.txt — frozen runtime на синтетическом входе, не метрика качества.
- load.json/load-final.txt — итоговая последовательная нагрузка; load-initial.json — ранний замер.
- resources-before/after.jsonl — два снимка Docker stats, не peak CPU/RAM.
- backup*.txt, restore.txt, restored-smoke.txt — копия, отказ/rotation, новая БД, smoke;
  backup-metadata.txt — проверка чтения безопасных меток и закрытости dump.
- tls.json — TLS1.2/1.3/1.1 и заголовки на локальном тестовом сертификате.
- public-demo.json, railway-services.json — read-only cloud snapshot;
  submission-links.json — анонимная проверка ссылок GitHub/demo.
- browser-availability.json — Chrome version и отсутствие Яндекса в стандартных путях.
- docs-validation.json — ссылки актуальных документов и проверка текущего diff.

Файлы *initial* и исходный отказ clean-deployment оставлены намеренно; причины и
условия повторов описаны в приёмке. Нет замены провала предполагаемым PASS.
Playwright traces/cookies и local env/пароли не включены в evidence.
Windows-пути в логах относятся к машине проверки, а не к условиям развёртывания.

reports-large.json и report-first/last.png — независимая проверка 5050 синтетических заявок, фактического лимита 5000, кириллицы и metadata; визуально проверены две страницы.
clean-final-refresh.txt — локальный fast-forward clean clone до 50cbdd9 и пересборка/backup marker.
compose-config.txt — base/profiles, mock и TLS config валидны.

public-demo-read-account.json — manager login/read/logout/401, 79 объектов, 403 для privileged reads. Только имена полей/агрегаты; cookie, CSRF token и пароль не сохранены.
Текстовые логи сохранены с нормализованными переносами строк и концевыми пробелами; строки результатов и отказов не удалялись.
