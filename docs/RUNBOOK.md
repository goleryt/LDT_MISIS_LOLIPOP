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

Python 3.14, Node 24, PostgreSQL 16 (ТЗ допускает 12+, текущая проверка проводится на 16 и 18).
Backend: создать venv, pip install -r requirements-dev.txt; заполнить .env; alembic upgrade head; uvicorn app.main:app --host 127.0.0.1 --port 8000.
Frontend: npm ci; npm run dev. Vite проксирует /api, /health, /ready в backend. VITE_API_BASE_URL по умолчанию пустой (один origin).
Для API-клиентов: войти через /auth/login, сохранить cookie, передавать полученный csrf_token как X-CSRF-Token при изменениях.

## Обновление существующей установки

Перед обновлением сделать и проверить backup. Сохранить .env отдельно от исходников.
Обновить код, установить закреплённые зависимости, применить alembic upgrade head, проверить /ready и вход.
Новые миграции продолжают цепочку 7bb10cf49ac2; существующие события/заявки не удаляются.
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
`cd backend && python -m scripts.run_ml_daily [--date YYYY-MM-DD]` — раз в сутки после закрытия суток; без даты берутся последние закрытые сутки. Повтор за тот же день заменяет результат.
Отказ `INSUFFICIENT_HISTORY` означает историю журнала меньше 401 суток; расчёт по короткой истории намеренно не выполняется. Расписание (cron/systemd) настраивается при развёртывании.
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
Нагрузочный тест задаёт 20 одновременно работающих HTTP-клиентов; публикует p50/p95 и сравнение с одним пользователем. Пороги теста (p95<2с, рост<5 раз) — инженерный критерий этой поставки, а не согласованный с заказчиком SLA.

Источники: [pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html), [Playwright browsers](https://playwright.dev/docs/browsers).
