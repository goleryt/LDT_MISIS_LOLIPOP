# Сборка, запуск, обновление и восстановление

## Быстрый запуск Docker/Linux

Требуются Docker Engine и Compose 2.24.4+ (для !override в TLS-конфигурации).
Из корня репозитория:
1. Скопировать backend/.env.example в backend/.env, задать случайный POSTGRES_PASSWORD.
2. Выполнить docker compose --env-file backend/.env -f infra/compose.yaml up --build -d.
3. Создать пользователя: docker compose --env-file backend/.env -f infra/compose.yaml exec backend python -m app.admin create-user admin --role admin.
4. Открыть http://localhost:8080 и войти. Пароль вводится интерактивно.
5. Загрузить справочники объектов/каналов и события через раздел импорта.

Сервис migrate применяет Alembic перед запуском API. Нет create_all на старте приложения.
Газовая модель подключена отдельным профилем ml. До первого подтверждённого суточного
расчёта журнал прогнозов пуст. Запуск, маркер полноты и ревизии: ML_INTEGRATION_RU.md.

Если Docker Hub недоступен, build args PYTHON_IMAGE / NODE_IMAGE / NGINX_IMAGE позволяют использовать одобренное зеркало. Проверки этой поставки использовали public.ecr.aws/docker/library для тех же официальных образов. Не изменяйте глобальные настройки Docker ради отдельного проекта.

## Локальная разработка

Python 3.14, Node 24, PostgreSQL 16 (ТЗ допускает 12+; октябрьская проверка проведена на 16, а проверка 18 относится к историческому отчёту).
Backend: создать venv, pip install -r requirements-dev.txt; заполнить .env; alembic upgrade head; uvicorn app.main:app --host 127.0.0.1 --port 8000.
Frontend: npm ci; npm run dev. Vite проксирует /api, /health, /ready в backend. VITE_API_BASE_URL по умолчанию пустой (один origin).
Для API-клиентов: войти через /auth/login, сохранить cookie, передавать полученный csrf_token как X-CSRF-Token при изменениях.

## Обновление существующей установки

Перед обновлением сделать и проверить backup. Сохранить .env отдельно от исходников.
Обновить код, установить закреплённые зависимости, применить alembic upgrade head, проверить /ready и вход.
Текущая head — d01602, цепочка продолжает c92601 через d01601; существующие события/заявки не удаляются.
Откат новых миграций удаляет новые доменные таблицы и историю в них; в эксплуатации предпочтительно восстановление проверенной резервной копии в новую БД.

## HTTPS

Разместить сертификат fullchain.pem и ключ privkey.pem в infra/certs (каталог исключён из Git).
Установить ENVIRONMENT=production, SECURE_COOKIES=true, ALLOWED_HOSTS с вашим DNS-именем и CORS_ORIGINS с точным HTTPS origin.
Запустить с -f infra/compose.yaml -f infra/compose.tls.yaml. Порт 80 перенаправляет в HTTPS, 443 обслуживает TLS 1.2/1.3.
Сертификат, DNS, сетевые ACL, права к секретам и обновление сертификата предоставляет эксплуатационная команда.

## Backup

Контейнер backup сразу создаёт pg_dump custom и затем повторяет ежедневно, хранит 14 дней.
Файл сначала .partial; после проверки pg_restore --list переименовывается и получает SHA-256. last-success содержит время последней удачной копии.
Мониторинг должен сигнализировать при возрасте last-success >26 часов или перезапуске backup.
Том backups на том же узле защищает от ошибки БД, но не от потери узла: заказчик настраивает копирование на отдельное защищённое хранилище.
Ручной запуск: docker compose --env-file backend/.env -f infra/compose.yaml exec backup sh /scripts/backup.sh.

## Restore

В контейнере backup: sh /scripts/restore.sh /backups/ldt-TIMESTAMP.dump NEW_DATABASE.
Скрипт проверяет SHA-256, создаёт новую пустую БД и выполняет pg_restore --single-transaction --exit-on-error.
Исходная БД не удаляется. При существующей целевой БД операция останавливается.
Проверить counts, Alembic, вход, карту и последние события на восстановленной БД; затем в согласованное окно переключить POSTGRES_DB.
Сохранить время начала/окончания и результат проверки. Цель ТЗ ≤4 ч подтверждается на реальном объёме и оборудовании заказчика; измерение маленького тестового массива не доказывает RTO промышленной БД.

## Суточный ML-расчёт

Окружение: Python 3.12, `pip install -r backend/requirements-ml.txt` (на macOS для lightgbm нужен libomp). Бандлы пакета — в `models/bundles/` (или `ML_BUNDLES_DIR`).
`cd backend && python -m scripts.run_ml_daily [--date YYYY-MM-DD]` — раз в сутки после закрытия суток; без даты берутся последние закрытые сутки. Нужен маркер завершения суток; повтор с теми же входами идемпотентен, изменённые входы требуют новой ревизии. Предыдущие решения не перезаписываются.
Отказ `INSUFFICIENT_HISTORY` означает историю журнала меньше 401 суток; расчёт по короткой истории намеренно не выполняется. В Compose профиль `ml` запускает scheduler. Он ждёт маркер в `data/ml-ready`; сам по себе running-процесс не доказывает успешный расчёт.
Подробности и смысл оценки: docs/ML_INTEGRATION_RU.md.

## Диагностика

/health — процесс, /ready — БД/миграции.
/api/v1/integrations/status — успех/ошибка/курсор источника.
/api/v1/audit — журнал действий (admin).
POST /predictions/inference всегда отвечает 503: прогнозы считаются суточной задачей, не по запросу. GET /predictions/status показывает дату последнего расчёта (`no_ml_run_yet`, пока задача не запускалась).
401 — истёк/отсутствует сеанс; 403 — роль/CSRF; 409 — конфликт состояния; 422 — неверные данные.
После 503 при изменении сущности обновить её состояние перед повтором: бизнес-транзакция могла завершиться до сбоя записи результата аудита.

## Проверки

ENVIRONMENT=test и отдельная POSTGRES_DB=ldt_test обязательны для pytest: тестовые таблицы очищаются.
alembic upgrade head; alembic check; pytest -q.
npm ci; npm run lint; npm run build.
Для smoke/load заполнить TEST_USERNAME, TEST_PASSWORD, BASE_URL и запустить tests/smoke.py / tests/load.py.
Тестовые данные: только ENVIRONMENT=test, python -m scripts.seed_test_data. Это 50 тестовых объектов, 1000 датчиков, 20000 фактических синтетических наблюдений; прогнозов нет.
Браузеры: npx playwright test --project=chrome. Для Яндекс.Браузера установить YANDEX_BROWSER_PATH на исполняемый файл и выполнить --project=yandex. Используется отдельный временный профиль, не основной профиль пользователя.
Нагрузочный тест последовательно измеряет baseline 1 пользователя, 20 читателей и 20 смешанных пользователей (чтение → создание заявки → in_progress → completed). Публикует requests/errors/error_rate/p50/p95/p99/RPS. Произвольных порогов деградации нет; успешное завершение означает отсутствие HTTP/transport ошибок. Изменяющая нагрузка разрешена только на loopback и должна выполняться на отдельной БД. Это короткий приёмочный профиль, не endurance-тест.

Источники: [pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html), [Playwright browsers](https://playwright.dev/docs/browsers).

## Operations и резервные копии: октябрьское обновление

Admin `GET /api/v1/operations/status` читает только служебные метаданные:
API/DB, last_seen/last_success scheduler и integration worker, последний импорт,
последний prediction job, ошибки интеграций, pool текущего API-процесса, backup.
Проверять возраст last_seen/last_success: сохранённое idle не гарантирует, что процесс сейчас запущен.
`not_observed`/`not_configured` и null означают отсутствие подтверждения, не успех.

Backend получает `/backup-status` read-only из тома backups. `status.json` хранит
running/completed/failed; `last-success` сохраняет только последнюю успешную попытку.
Неудачная попытка удаляет свой partial, не стирает предыдущий успех.
Checksum записан с относительным именем: dump и .sha256 можно переносить вместе.
Restore в существующую БД запрещён. Rotation проверена на собственных старых тестовых файлах.
Измерение 16.10: 200000 событий, новая БД, restore 1 с, smoke успешен.
Это не RTO полного 12-летнего архива и не offsite backup.

## Чистое развёртывание и конфигурация

Октябрьская проверка выполнена из локального Git clone ветки на commit 860c15b,
с новыми томами, Alembic и seed 20000 событий; smoke и Chrome подтверждены в evidence. После fast-forward до 50cbdd9 проверены три Chrome flow и исправленные backup-метки.
Сборка использует кеш зависимостей Docker, а не старый DB volume.
Переменные окружения оболочки имеют приоритет над `--env-file` в Compose:
перед запуском проверьте отсутствие конфликтующих POSTGRES_* без вывода их секретных значений.
Первый тестовый запуск выявил именно такой конфликт; он сохранён в журнале приёмки.

Тесты pytest очищают таблицы! Только отдельные ENVIRONMENT=test / POSTGRES_DB=ldt_test.
Не направлять их на рабочий demo, даже если имя БД совпадает. Load/E2E также создают тестовые заявки.
Для `seed_test_data` пароль передаётся через TEST_PASSWORD, а не Git/аргументы команд.

## Публичное demo

Railway HTTPS root/health/ready отвечали 200 16.10.2026; anonymous events — 401.
Облачные API и PostgreSQL running; отдельный ml-demo-job остановлен после расчёта,
постоянных scheduler/integration services нет. Новые RC-коммиты не публиковались,
деплой и push требуют отдельного разрешения владельца. Manager login/read/logout и запрет admin API проверены; остальные demo-роли/полноту данных проверить вручную перед показом. Локальная приёмка не заменяет приёмку облачной версии.

## Release candidate

Текущая ветка `release/final-rc`, application/test commit `f7d1d05`.
Cloud build с APP_COMMIT и smoke +3 Chrome flows подтверждены:
[идентификатор](evidence/release-rc/application-commit.txt),
[build](evidence/release-rc/cloud-build-commit.txt),
[smoke](evidence/release-rc/cloud-commit-smoke.txt),
[Chrome](evidence/release-rc/chrome-commit.txt).
Чистый QA использует отдельные volumes, 20000 наблюдений, без вымышленных прогнозов.
Свежая резервная копия: 200371 событие, checksum, новая БД, restore3с, API smoke.
Первая автоматическая копия теперь ждёт migrate.

Полный workflow отдельного staging и необходимые ручные действия:
[DEPLOYMENT_RC](DEPLOYMENT_RC.md). Web image не запускает scheduler/worker/backup
и не применяет миграции автоматически; pre-deploy выполняется отдельно.
Backend tests исключены из runtime-образов. Для вспомогательного
`scripts/run_container_tests.sh` нужно отдельно read-only смонтировать
`backend/tests` в `/app/tests` контейнера, подключённого только к disposable test DB.
Обычный поддержанный путь regression: requirements-dev и pytest из исходников.
Не запускать этот helper на demo/production DB.
