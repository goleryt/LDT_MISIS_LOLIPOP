# Материалы финала — release/final-rc

Актуальное дополнение20.10.2026: [финальный командный UI](VISUAL_BRANCH_INTEGRATION_2026-10.md),
[import supplement](IMPORT_VISUAL_SUPPLEMENT_2026-10-20.md),
[delivery](DELIVERY_VISUAL_2026-10-20.md). Functional18af8fa опубликован на существующем
Railway, deploymentb1bd6fee-0e94-46b9-8d76-11b555c8e06f, actual CI39408268560 PASS. Последующий documentation-only
tip получает отдельные CI и rollout; final tag не создаётся.

Состояние 20.10.2026, Europe/Moscow. Наличие документа не заменяет evidence.

Дополнение к RC: [team UI review](DESIGN_BRANCH_REVIEW_2026-10.md),
[UI/import acceptance](UI_BUGFIX_ACCEPTANCE_2026-10.md),
[scenario integration](ML_COMBINED_INTEGRATION_RU.md),
[scenario acceptance](ML_COMBINED_ACCEPTANCE_RU.md). Новые модули проверены в
изолированном QA и опубликованы отдельными Stage A/B; SF/Fire явно включены в
demo на помеченной синтетике. [Public evidence](RAILWAY_RELEASE_ACCEPTANCE_2026-10.md).
Затем отдельно проверен [CSV/XLSX load gate](IMPORT_LOAD_ACCEPTANCE_2026-10-20.md).
Актуальность ветки не заменяет проверку фактического deployment SHA.

| Артефакт | Статус / наличие | Действие перед сдачей |
|---|---|---|
| Git repository / RC branch | READY — [repository](https://github.com/goleryt/LDT_MISIS_LOLIPOP/tree/release/final-rc), branch опубликована | Использовать утверждённый RC SHA; main не объединялся |
| RC commit | READY — git rev-parse origin/release/final-rc; functional UI18af8fa | Public runtime идентифицируется в Railway evidence; final tag не создаётся |
| Final tag | NOT APPLICABLE | Не создавался по инструкции владельца |
| GitHub Actions | READY — [PASS run39408268560](https://github.com/goleryt/LDT_MISIS_LOLIPOP/actions/runs/39408268560),18af8fa, все4jobs | Documentation-only tip проверяется отдельно; не считать workflow-файл результатом CI |
| Railway/demo | READY в проверенном объёме — [live demo](https://ldt-demo-production.up.railway.app/) | Worker/scheduler/automatic backup отсутствуют; continuous industrial operation не заявляется |
| Demo credentials | READY — manager/dispatcher/technician/admin/analyst проверены; пароли вне Git | Владелец выдаёт доступ отдельно; не помещать credentials в evidence |
| Architecture | READY — [ARCHITECTURE](ARCHITECTURE.md) | Point, mock/production и shadow semantics разделены |
| Deployment instructions | READY — [DEPLOYMENT_RC](DEPLOYMENT_RC.md), [RUNBOOK](RUNBOOK.md) | Учитывать ограниченный trial/free credit и отсутствие фоновых сервисов |
| Acceptance evidence | READY — [FINAL_ACCEPTANCE](FINAL_ACCEPTANCE_2026-10.md), [public acceptance](RAILWAY_RELEASE_ACCEPTANCE_2026-10.md), [import gate](IMPORT_LOAD_ACCEPTANCE_2026-10-20.md) | Фактические SHA/run/deployment IDs и ограничения |
| Demo/browser checklist | READY — [BROWSER_ACCEPTANCE_RC](BROWSER_ACCEPTANCE_RC.md), [remote probe](../tests/remote/README.md) | Без fixture seed/inference против Railway |
| Presentation PPTX/PDF | **MISSING FINAL ARTIFACT** | Нужны утверждённые слайды и публичная ссылка |
| Accompanying DOCX/PDF | **MISSING FINAL ARTIFACT** | Нужен актуальный документ финальной версии; исторический PDF его не заменяет |
| Native Yandex evidence | **MISSING — NOT TESTED** | Яндекс отсутствует в среде; выполнить native remote checklist |
| Physical touchpad evidence | **MISSING — MANUAL TOUCHPAD VERIFICATION REQUIRED** | Synthetic remote pinch PASS; физический жест проверить вручную |

AD/CA, реальные внешние источники/полный архив/координаты, SIEM, постоянное offsite-
хранилище и промышленные нормативы требуют инфраструктуры заказчика. Не менять
материалы после применимого стоп-кода вне разрешённой процедуры финала.
Merge main и создание final tag этим этапом не выполнялись.

Итог этапа и перечень файлов: [DELIVERY_COMBINED_2026-10-19](DELIVERY_COMBINED_2026-10-19.md).
