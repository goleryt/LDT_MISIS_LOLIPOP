# Изменения финального этапа — release/final-rc

Исходные 11 commits до a5ba6e0 сохранены без squash/rebase/смены hashes.
Их история: `git log 5d64126..a5ba6e0`. Они ранее опубликованы в старой ветке.
Новые RC commits локальные; main и Railway не менялись, push не выполнялся.
Итоговый documentation HEAD проверяется `git rev-parse HEAD`; application commit f7d1d05.

| RC commit | Содержание |
|---|---|
| 13c58c5 | Оптимистическая версия заявки,409 при устаревшей правке, версия в UI |
| e539a8c | Guard backup metadata, version/commit diagnostics |
| a877612 | Строгий integration envelope/cursor и recovery tests |
| ce14dcc | Polling/read race, prediction URL/Back, version/form sync, visual QA |
| 9fdf37f | Настоящие одновременные правки: один успех/один конфликт |
| 36d7aa9 | Первая автоматическая копия после миграции |
| d3d15cd | Отдельный cloud web Docker/launcher/nginx, Tini, readonly QA, CI packaging smoke |
| f7d1d05 | Mixed load передаёт версию заявки |

Следующий documentation/evidence commit не меняет исполняемый код.
[Список файлов](evidence/release-rc/changed-files.txt) включает новые evidence;
[предыдущий список](evidence/2026-10-16/changed-files.txt) описывает первый этап.
Это перечни уже внесённых изменений, не файлы для ручной замены.

Результаты: [FINAL_ACCEPTANCE_2026-10](FINAL_ACCEPTANCE_2026-10.md).
ML paths unchanged: [ml-frozen](evidence/release-rc/ml-frozen.txt).
108 backend PASS; frontend build PASS/lint10warnings; Chrome11+3+4 PASS;
load918/0errors; restore200371events→newDB→smokePASS.
Yandex и remote RC NOT TESTED; промышленная инфраструктура — внешняя зависимость.
