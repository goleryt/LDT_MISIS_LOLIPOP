# Развёртывание release/final-rc

19.10.2026: RC опубликован на существующий demo Railway с разрешения владельца.
Проверены CI, runtime commit, миграция до d01602, HTTPS и основные remote flows:
[фактическая приёмка](REMOTE_RC_ACCEPTANCE_2026-10-19.md).
Main не менялся. Платный тариф и неизвестные production secrets не менялись.

Фактический deployment: tracked-only `git archive release/final-rc` → CLI upload в
существующий ldt-demo / production / fortunate-communication. Существующая PostgreSQL
сохранена; перед additive upgrade сделан pg_dump18, скачан вне Git, checksum совпал.
Pre-deploy: `alembic upgrade head`, Dockerfile: `infra/Dockerfile.cloud`, health: `/ready`.
APP_COMMIT передаётся точным SHA загружаемого archive, с `--skip-deploys` до явного `up`.
Нельзя повторно загружать старый archive с новым APP_COMMIT: идентификатор должен
соответствовать реальному исходному коду. Версия подтверждается через admin operations.

**EXTERNAL MANUAL ACTION REQUIRED** остаётся для persistent integration worker,
scheduler и automatic/offsite backup, которые в текущем Railway не развёрнуты.
Инструкция отдельного staging ниже — вариант новой изолированной установки, а не
описание уже созданных сервисов. Не создавать платные сервисы без согласования.

## Что подготовлено

`infra/Dockerfile.cloud` собирается из корня: React/Vite → nginx + Python API.
Публичный процесс слушает PORT (8080 по умолчанию), API — только 127.0.0.1:8000.
Контейнер работает от uid10001, Tini пересылает сигналы и собирает дочерние процессы.
Если API/nginx прекращает работу, основной процесс завершает контейнер с ошибкой.
Readiness проверяет БД и head Alembic. Источник app version/commit доступен admin
через `/api/v1/operations/status`, без credentials.

На старте **нет** seed, миграции или inference. Тестовые CSV и модельные бандлы
не вшиты в web-образ. Импорт/restore — отдельное осознанное действие администратора.
Команда миграции: `alembic upgrade head`; выполнять один раз до web/worker.

## Воспроизводимая локальная QA

Требуются Docker/Compose, свободный loopback-порт 18091, отдельная конфигурация
`backend/.env` из примера с собственным случайным паролем PostgreSQL.
Не переиспользовать production env/тома. Пример ниже не публикует сервис в интернет.

Из корня, PowerShell:

```powershell
docker build -f infra/Dockerfile.cloud -t ldt-cloud-qa .
docker compose --env-file backend/.env -p ldt-rc-qa -f infra/compose.cloud-qa.yaml --profile mocks up -d --wait
docker compose --env-file backend/.env -p ldt-rc-qa -f infra/compose.cloud-qa.yaml exec web python -m app.admin create-user qa-dispatcher --role dispatcher
```

Пароль вводится интерактивно, не в Git и не в аргументах. Открыть
`http://127.0.0.1:18091`. Затем импортировать объекты → каналы → события через UI.
Для CI/изолированного QA вместо импорта разрешён `scripts.seed_test_data` с
TEST_USERNAME/TEST_PASSWORD через окружение; создаются только наблюдения, без прогнозов.
Pytest очищает таблицы: не запускать его на этом стенде с полезными данными.

Профиль mocks: equipment/СМВУ/ОДС/weather/work_status. Для последнего сначала
создать обычную тестовую заявку, передать её ID как MOCK_REQUEST_ID и пересоздать
только mock-source. Источник создаёт новые mock-наблюдения, не ML-результаты.
Worker не имеет HTTP healthcheck; проверить last_seen/last_success/cursor/errors
в admin operations. Running-процесс сам по себе не доказывает успешный обмен.

QA Compose содержит свои именованные volumes; они сохраняются после остановки.
Не выполнять down -v, volume prune или удаление чужих данных.
Автоматический backup ждёт migrate, поэтому первая копия уже содержит схему.

## Railway staging: точная последовательность после разрешения

1. Проверить доступный бесплатный лимит аккаунта. Создание дополнительных сервисов
   и бессрочная бесплатная работа не гарантируются. Не включать платный тариф автоматически.
2. Выбрать отдельное окружение, например staging-rc. Создать отдельные PostgreSQL и
   web service, например ldt-rc-web. Не подменять production DB/секреты/домен.
3. У web выбрать root репозитория и Dockerfile `infra/Dockerfile.cloud`.
   Это обычный Docker image; инструкции не зависят от устаревающего railway.json.
4. Настроить private PostgreSQL параметры из reference variables нового PostgreSQL.
   Приложение использует POSTGRES_HOST/PORT/DB/USER/PASSWORD/SSLMODE, а не DATABASE_URL.
   Шаблон полей без секретов — `infra/cloud.env.example`.
5. Задать ENVIRONMENT=production, SECURE_COOKIES=true, ALLOW_MOCK_INGESTION=false,
   AUTH_PROVIDER=local либо отдельно проверенный LDAPS. Для этого этапа не подключать
   промышленные источники заказчика.
6. Создать домен staging, указать точные ALLOWED_HOSTS и HTTPS CORS_ORIGINS.
   Если RAILWAY_PUBLIC_DOMAIN доступен, launcher подставит безопасные defaults;
   явно заданные значения не перезаписываются. TLS завершается на стороне Railway.
7. Pre-deploy command: `alembic upgrade head`. Healthcheck path: `/ready`.
   Проверить успех pre-deploy перед стартом worker. На ошибке миграции не продолжать.
8. Start command оставить из образа: `python -m scripts.start_cloud`.
   PORT должен отличаться от 8000 и быть в диапазоне 1024..65535.
   WEB_CONCURRENCY по умолчанию 2; локальные нагрузочные результаты получены при 4.
   Не заявлять их для другой конфигурации/лимитов памяти без измерения.
9. Источник кода — release/final-rc, конкретный утверждённый commit. Чтобы передать
   код без GitHub-интеграции, после разрешения можно использовать CLI:
   `railway up --service ldt-rc-web --environment staging-rc`.
   До этой команды перепроверить выбранный проект/окружение. Для существующего demo
   CLI upload выполнен; service/DB identifiers и результат записаны в remote acceptance.
10. После запуска создать отдельные demo-пользователи через `python -m app.admin create-user`
    с ролями manager/dispatcher/technician/admin и передать пароли владельцу вне Git.
    Не создавать их из предсказуемого пароля в deploy script.
11. Загрузить согласованный обезличенный журнал либо восстановить утверждённый snapshot
    в **новую** БД. Для демонстрации ML допустим сохранённый ранее реальный результат
    с его provenance; пустой журнал нельзя заполнять вымышленными вероятностями.
12. Выполнить remote checklist ниже, сохранить URL, commit, дату, версии браузеров и результаты.
    Только затем считать remote RC проверенным. Откат к старому образу не отменяет
    миграции; при необходимости восстанавливать backup в новую БД, без удаления исходной.

## Фоновые процессы и данные

- Integration worker — отдельный service/процесс с `python -m app.integration_worker`,
  теми же private DB параметрами и read-only файлом источников. HTTP mock разрешён
  только в ENVIRONMENT=test/development; не ослаблять production guard ради демо.
  Для mock-демонстрации использовать отдельный QA, ясно обозначенный как тестовый.
- ML scheduler не включён в web. Существующий образ Python3.12/замороженный бандл/
  готовый marker подключаются отдельно по ML_INTEGRATION_RU.md. Этот этап не меняет
  ML и не генерирует новый inference для наполнения стенда.
- Backup — отдельный процесс с pg_dump, защищённым persistent volume и копированием
  вне узла. Без подключения такого хранилища operations покажет not_configured.
  Не выдавать root filesystem cloud-контейнера за постоянное backup-хранилище.

## Remote checklist

Основной remote checklist выполнен 19.10; точный объём и оставшиеся проверки
разделены в remote acceptance. При повторении использовать утверждённый demo/staging
URL и commit, не запускать обычный fixture suite против его БД:

Login manager → map → object → sensor → chart/history → refresh/deep link/Back.
Alarm → точный sensor; notification → entity → read → refresh → другой пользователь.
Dispatcher → сохранённый prediction → detail → decision → recommendation → draft →
правка → confirmation → in_progress → completed/cancelled. Импорт четырёх форматов →
registry/duplicate/ошибка. PDF/XLSX с периодом и источником. Technician не подтверждает
draft; manager не пишет; admin видит audit/operations. Прямые REST 401/403/CSRF,
истечение сессии, logout и вход другой ролью. Сетевой отказ → feedback → recovery.

HTTPS health/ready, API DB, last_seen/last_success источников, last import/job/backup,
app version/commit должны быть зафиксированы отдельно. При отсутствии marker/job
записывать это как отсутствие расчёта, а не успешную работу scheduler.

Основания provider-настроек: [Railway Dockerfiles](https://docs.railway.com/guides/dockerfiles),
[pre-deploy](https://docs.railway.com/deployments/pre-deploy-command),
[health checks](https://docs.railway.com/deployments/healthchecks).
Актуальность этих инструкций проверять перед реальной публикацией.
