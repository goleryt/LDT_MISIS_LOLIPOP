# Материалы финала — release/final-rc

Состояние 16.10.2026. Этот inventory не утверждает готовность отсутствующих файлов.

| Артефакт | Наличие | Действие перед сдачей |
|---|---|---|
| Git repository | https://github.com/goleryt/LDT_MISIS_LOLIPOP | RC локален; отдельно разрешить push/merge и проверить публичные права |
| Final commit | Application `f7d1d05`; итоговый documentation HEAD — `git rev-parse HEAD` | Записать точный утверждённый HEAD в форму; release tag не создан |
| Live demo | https://ldt-demo-production.up.railway.app/ — старая сентябрьская версия | Публикация RC не выполнялась; EXTERNAL MANUAL ACTION REQUIRED |
| Demo credentials | Выдаёт владелец вне Git | Проверить нужные роли на утверждённом staging; не помещать пароли в evidence |
| Presentation PPTX/PDF | **MISSING FINAL ARTIFACT** в текущем репозитории | Предоставить утверждённые слайды и публичную ссылку, проверить доступ без входа |
| Актуальная accompanying DOCX/PDF | **MISSING FINAL ARTIFACT** в текущем репозитории | Подготовить из проверенной документации; исторический внешний PDF не считать актуальным RC |
| Architecture | [ARCHITECTURE](ARCHITECTURE.md) | Сверить с утверждённым commit |
| Security / RBAC | [SECURITY](SECURITY.md) | Корпоративный AD и CA проверяются отдельно |
| Acceptance evidence | [FINAL_ACCEPTANCE_2026-10](FINAL_ACCEPTANCE_2026-10.md), evidence/release-rc | Сохранить вместе с версией кода |
| Deployment instructions | [DEPLOYMENT_RC](DEPLOYMENT_RC.md), [RUNBOOK](RUNBOOK.md) | Отдельное staging, новая БД, разрешение публикации и бесплатные лимиты |
| Demo/browser checklist | [BROWSER_ACCEPTANCE_RC](BROWSER_ACCEPTANCE_RC.md) | Нативный Яндекс + полный remote smoke, зафиксировать версии и дату |

Публичная ссылка старого demo не доказывает наличие новых RC-исправлений в облаке.
После утверждения публикации проверить все ссылки инкогнито. Не менять сданные
материалы после применимого стоп-кода без разрешённой организаторами процедуры финала.
