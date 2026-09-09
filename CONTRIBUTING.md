\# Правила работы с репозиторием



\## Основная ветка



В ветку `main` напрямую не коммитим.



Для каждой задачи создаём отдельную ветку:



\- `feature/<область>-<задача>` — новая функциональность

\- `fix/<область>-<проблема>` — исправление ошибки

\- `docs/<задача>` — документация

\- `chore/<задача>` — настройки и обслуживание проекта



Примеры:



\- `feature/ml-sensor-failure`

\- `feature/backend-upload`

\- `feature/frontend-dashboard`

\- `docs/demo-script`



\## Начало работы



Перед началом задачи:



```bash

git switch main

git pull --ff-only origin main

git switch -c feature/my-task

