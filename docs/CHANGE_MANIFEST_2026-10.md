# Изменения финального этапа — 16.10.2026

Ветка `final/non-ml-hardening-20261016`, база main `5d64126`.
Все перечисленные commits локальные. Main, исходный пользовательский checkout и Railway не обновлялись.
Последний commit с этой документацией/evidence перечисляется командой `git log origin/main..HEAD`;
его окончательный hash сообщён в итоговом ответе, чтобы не создавать самоссылочную запись hash внутри коммита.

| Commit | Содержание |
|---|---|
| 6f3c06e | fix: align request draft workflow with specification |
| 81c3a0b | fix: attribute audit records and expose operational worker status |
| fbaa3bc | fix: commit import data and registry atomically with retry coverage |
| 9cccb68 | fix: clarify monitoring UX and verify integration and report contracts |
| 9a834ff | test: verify LDAP transport and complete CI draft acceptance flow |
| 861f010 | fix: complete import selection and recoverable UI feedback |
| 860c15b | fix: expose backup failures and measure complete local load profiles |
| 6493c52 | fix: make backup health metadata readable by unprivileged API |
| 1c843ad | test: verify map interactions and compact Chrome navigation |
| 50cbdd9 | fix: explain empty map and expose report progress with safe errors |

## Исправления

- Draft из рекомендации, допустимые переходы, редактирование/подтверждение, история и идемпотентная связь.
- Атрибуция audit, строгий CSRF, матрица backend прав, LDAPS contract/no fallback, operations heartbeat.
- Атомарность import данных и успешного registry-статуса, retry после исключения/прерывания.
- Пять mock GET-источников, cursor/error/retry/upsert, точная ссылка уведомления и индивидуальный read.
- Честные названия фактического состояния карты и локальных заявок, ошибки/timeout/retry/progress,
  поддержанные форматы в UI, общий экран восстановления React; удалены два неиспользуемых frontend файла.
- Отчётные metadata, пустой/усечённый/большой экспорт, backup failure/checksum/rotation/status,
  безопасные права metadata, read-only mount API и защита Docker build context от env-файлов.
- Свежие 82 backend / 8 Chrome tests, clean clone/startup, нагрузка, restore 200000 событий,
  документация и честная матрица ограничений. Математика frozen ML не менялась.

## Полный список файлов

[changed-files.txt](evidence/2026-10-16/changed-files.txt) содержит все пути относительно корня,
включая документацию и evidence. Пути не являются инструкцией для ручного переноса:
изменения уже внесены и закоммичены в этой ветке.

Результаты сборок/тестов, Docker, миграций, нагрузки, backup, браузеров и безопасности:
[FINAL_ACCEPTANCE_2026-10](FINAL_ACCEPTANCE_2026-10.md).
PARTIAL/NOT TESTED, внешние зависимости и ручные проверки перечислены там явно.
