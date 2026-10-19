# Материалы финала — release/final-rc

Состояние 19.10.2026, Europe/Moscow. Наличие документа не заменяет evidence.

Дополнение к RC: [team UI review](DESIGN_BRANCH_REVIEW_2026-10.md),
[UI/import acceptance](UI_BUGFIX_ACCEPTANCE_2026-10.md),
[scenario integration](ML_COMBINED_INTEGRATION_RU.md),
[scenario acceptance](ML_COMBINED_ACCEPTANCE_RU.md). Новые модули проверены в
изолированном QA; публичный Railway пока остаётся14aad86, flags новых моделей
не включались. Актуальность ветки не означает актуальность публичного deployment.

| Артефакт | Статус / наличие | Действие перед сдачей |
|---|---|---|
| Git repository / RC branch | READY — [repository](https://github.com/goleryt/LDT_MISIS_LOLIPOP/tree/release/final-rc), branch опубликована | Использовать утверждённый RC SHA; main не объединялся |
| Final commit | READY — git rev-parse origin/release/final-rc; основной smoke ee16251, правка периода отчёта d4f3e09 проверена удалённо | Итоговый documentation/evidence commit проверяется CI и повторно публикуется перед завершением |
| Final tag | NOT APPLICABLE | Не создавался по инструкции владельца |
| GitHub Actions | READY — [PASS run39175260469](https://github.com/goleryt/LDT_MISIS_LOLIPOP/actions/runs/39175260469), 6ca2a44, включает report fix | Проверить также run окончательного documentation RC HEAD |
| Railway/demo | READY в проверенном объёме — [live demo](https://ldt-demo-production.up.railway.app/) | Worker/scheduler/automatic backup отсутствуют; continuous industrial operation не заявляется |
| Demo credentials | READY — manager/dispatcher/technician/admin/analyst проверены; пароли вне Git | Владелец выдаёт доступ отдельно; не помещать credentials в evidence |
| Architecture | READY — [ARCHITECTURE](ARCHITECTURE.md) | Point, mock/production и shadow semantics разделены |
| Deployment instructions | READY — [DEPLOYMENT_RC](DEPLOYMENT_RC.md), [RUNBOOK](RUNBOOK.md) | Учитывать ограниченный trial/free credit и отсутствие фоновых сервисов |
| Acceptance evidence | READY — [FINAL_ACCEPTANCE](FINAL_ACCEPTANCE_2026-10.md), [remote acceptance](REMOTE_RC_ACCEPTANCE_2026-10-19.md) | Фактические SHA/run/deployment IDs и ограничения |
| Demo/browser checklist | READY — [BROWSER_ACCEPTANCE_RC](BROWSER_ACCEPTANCE_RC.md), [remote probe](../tests/remote/README.md) | Без fixture seed/inference против Railway |
| Presentation PPTX/PDF | **MISSING FINAL ARTIFACT** | Нужны утверждённые слайды и публичная ссылка |
| Accompanying DOCX/PDF | **MISSING FINAL ARTIFACT** | Нужен актуальный документ финальной версии; исторический PDF его не заменяет |
| Native Yandex evidence | **MISSING — NOT TESTED** | Яндекс отсутствует в среде; выполнить native remote checklist |
| Physical touchpad evidence | **MISSING — MANUAL TOUCHPAD VERIFICATION REQUIRED** | Synthetic remote pinch PASS; физический жест проверить вручную |

AD/CA, реальные внешние источники/полный архив/координаты, SIEM, постоянное offsite-
хранилище и промышленные нормативы требуют инфраструктуры заказчика. Не менять
материалы после применимого стоп-кода вне разрешённой процедуры финала.
Merge main и создание final tag этим этапом не выполнялись.
