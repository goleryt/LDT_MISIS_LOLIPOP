# Дополнение: конкурентные импорты и командный UI — 20.10.2026

Основная приёмка: [первый load gate](IMPORT_LOAD_ACCEPTANCE_2026-10-20.md).
Backend/infra/ML byte-identical к 237ff93; глобальные 2 DB slots, nginx admission,
429/409 + безопасный повтор, deadline и XLSX limits сохранены. Новая очередь не добавлялась.

## Новые измерения

Изолированные localhost:18094 / ldt_import_load_qa, PG18, web и DB по 1 GiB/2 vCPU.
Новый production frontend image; отдельная авторизованная сессия каждого пользователя.
CSV/XLSX чередуются в mixed. Запуски 5/10/20 не означают 20 одновременно исполняемых
SQL-транзакций: приняты два файла, остальные явно отклонены и повторены парами.

| Сценарий | Пользователи | Строк/файл | Первый ответ | Время всей серии, s | Web peak MiB | PG working set MiB | API p95 ms | API errors/requests |
|---|---:|---:|---|---:|---:|---:|---:|---|
| small mixed | 5 | 1000 | {'429': 3, '200': 2} | 2.95 | 292.29 | 120.46 | 416.67 | 0/12 |
| small mixed | 10 | 1000 | {'429': 8, '200': 2} | 6.08 | 319.94 | 146.19 | 264.5 | 0/33 |
| small mixed | 20 | 1000 | {'429': 18, '200': 2} | 10.46 | 318.66 | 144.92 | 429.19 | 0/48 |
| same-csv csv | 20 | 1000 | {'429': 16, '409': 3, '200': 1} | 1.48 | 272.3 | 135.89 | 89.75 | 0/9 |
| same-xlsx xlsx | 20 | 1000 | {'429': 16, '409': 3, '200': 1} | 1.62 | 274.84 | 156.96 | 125.43 | 0/12 |
| invalid-among-valid mixed | 20 | 1000 | {'429': 18, '200': 2} | 10.97 | 314.95 | 168.77 | 310.42 | 0/60 |
| larger mixed | 20 | 25000 | {'429': 18, '200': 2} | 227.53 | 408.51 | 468.0 | 480.55 | 0/951 |
| with-map mixed | 20 | 25000 | {'429': 18, '200': 2} | 227.71 | 383.28 | 460.94 | 528.09 | 0/837 |

Итого: 1962 обычных API запросов, 0 ошибок. Web peak 408.51 MiB; PG sampled memory.current peak 1023.88 MiB (включает file cache), working set peak 468.0 MiB.
CPU sampled max: web 202.07%, PG 102.81% от одного ядра; выделено по 2 vCPU. Целевые PG connections peak 11 включая одно соединение измерителя.
PG memory.peak в raw JSON накопительный с момента старта контейнера; это не новый
пик отдельного кейса. Working set исключает inactive_file; RAM клиента-генератора
и всего Windows host не измерялась. CPU рассчитан по отдельному timestamp каждого контейнера.

- Одинаковый файл: 20 пользователей CSV и XLSX, ровно 1000 итоговых строк; повторные ответы already_imported.
- Ошибочный последний файл: 19 completed / 1 failed, HTTP400 при retry; ровно19000 строк, никаких строк ошибочного файла.
- Крупная серия: 20 ×25000 =500000 новых строк. Большинство первых ответов429; каждый корректный файл затем завершён.
- При повторной крупной серии браузер действительно открыт до uploads, zoom +/- работает: 112 итераций, 0 page errors.
- Первый observer стартовал в момент намеренного QA restart и получил ERR_EMPTY_RESPONSE до первого импорта. Это ошибка оркестрации теста; сохранена отдельно, исправлена ready-handshake и проверена новой полной крупной серией.
- После всех операций: 0 idle-in-transaction / 0 held import slots / 0 registry processing; в audit20 разных actors.
- Во всех восьми кейсах 0 OOM / OOM kill, нет неожиданных HTTP/transport ошибок.429/409 backpressure и ожидаемый400 не считаются успешными импортами.

## Повторное использование проверок

CSV/XLSX/JSON/XML valid/invalid/duplicate/atomic rollback, RBAC/audit regression:151 pytest PASS.
Исходные kill/cancel/partial multipart/deadlock/oversized archive проверки повторно не запускались:
код backend/infra совпадает с их проверенным состоянием; source-identity.json и ссылки первого gate сохранены.
После process loss запись registry может требовать безопасного повторного выбора исходного файла;
UI объясняет повтор. Durable job queue и автоматическое recovery processing не заявляются.

## Границы

Все стрессовые и аварийные тесты только в собственной QA-БД; Railway не нагружался.
Текущий public web memory.max=999997440 bytes (~953.67 MiB), CPU2 vCPU; QA limit1 GiB немного выше.
Измеренный рабочий набор существенно ниже этих лимитов, но это не измерение public нагрузки.
Новые размеры CSV/XLSX:1000/25000 строк, плюс подтверждённый первый gate10000; это не доказательство
20 файлов максимальных50 MiB/250000 строк или промышленного12-летнего архива.

Reproduction: tests/import_load.py --distinct-users (19 дополнительных qa-import пользователей
заранее создать только в dedicated QA; credentials только через окружение). tests/import_map_watch.cjs
принимает IMPORT_MAP_READY_FILE; дождаться его до нагрузки. RUN_IMPORT_LOAD=true и loopback guard обязательны.

Evidence: [summary](evidence/visual-integration-2026-10-20/imports/summary.json),
[gate](evidence/visual-integration-2026-10-20/imports/gate.json),
[browser](evidence/visual-integration-2026-10-20/imports/browser-map.json),
[with-map](evidence/visual-integration-2026-10-20/imports/with-map/mixed-20-different.json),
[post-load](evidence/visual-integration-2026-10-20/imports/post-load.json).
