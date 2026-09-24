# Компоненты поставки

Среда: Python 3.14, Node.js 24, PostgreSQL 16 (также проверен 18), nginx 1.28. Контейнеры запускаются в Linux.

## Backend

Прямые зависимости закреплены в requirements.txt; тестовые — requirements-dev.txt. Транзитивные зависимости Python разрешаются установщиком; для промышленной поставки следует зафиксировать проверенные digest образов во внутреннем реестре.

```text
alembic==1.20.0
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.15.1
click==8.5.0
fastapi==0.141.1
greenlet==3.5.6
h11==0.16.0
httptools==0.8.0
idna==3.19
Mako==1.4.1
MarkupSafe==3.0.3
psycopg==3.3.5
psycopg-binary==3.3.5
pydantic==2.13.5
pydantic-settings==2.15.0
pydantic_core==2.46.5
python-dotenv==1.2.3
python-multipart==0.0.32
PyYAML==6.0.3
SQLAlchemy==2.0.53
starlette==1.6.0
typing-inspection==0.4.4
typing_extensions==4.16.0
tzdata==2026.4
uvicorn==0.53.0
watchfiles==1.2.0
websockets==17.1
openpyxl==3.1.5
defusedxml==0.7.1
ldap3==2.9.1
httpx==0.28.1
reportlab==5.0.1
```

## Frontend

Точные версии полного дерева зафиксированы package-lock.json; установка — npm ci.

| Компонент | Проверенная версия | Группа |
|---|---|---|
| lucide-react | 1.47.0 | dependencies |
| react | 19.3.0 | dependencies |
| react-dom | 19.3.0 | dependencies |
| react-router-dom | 7.18.4 | dependencies |
| recharts | 3.10.1 | dependencies |
| @playwright/test | 1.63.0 | devDependencies |
| @types/node | 24.13.6 | devDependencies |
| @types/react | 19.3.0 | devDependencies |
| @types/react-dom | 19.3.0 | devDependencies |
| @vitejs/plugin-react | 6.1.1 | devDependencies |
| oxlint | 1.85.0 | devDependencies |
| typescript | 6.0.3 | devDependencies |
| vite | 8.3.0 | devDependencies |

## Назначение

FastAPI/Pydantic — API и контракты; SQLAlchemy/psycopg/Alembic — PostgreSQL и миграции; ldap3 — LDAPS; defusedxml — безопасный XML; openpyxl — XLSX; ReportLab — PDF; httpx — чтение источников и проверки.

React/Router — интерфейс и навигация; Recharts — история показаний; Lucide — значки; Vite/TypeScript — сборка; Oxlint — статический анализ; Playwright — браузерные сценарии.

Noto Sans Regular включён для кириллицы в PDF. Источник: https://github.com/notofonts/noto-fonts/tree/main/hinted/ttf/NotoSans. Лицензия SIL Open Font License 1.1 находится рядом: backend/app/assets/FONT-LICENSE.txt.

## Контракты

- openapi.json — снимок HTTP API.
- integration-record.schema.json — входная запись источника; обязательность полей конкретного типа описана в INTEGRATIONS.md.
- prediction-result.schema.json — только схема результата будущей реальной модели, без примеров вымышленных вероятностей.
