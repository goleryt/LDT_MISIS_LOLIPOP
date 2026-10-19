# Team UI integration acceptance — 19 October 2026

Starting RC: `14aad86`. Source review: [DESIGN_BRANCH_REVIEW_2026-10.md](DESIGN_BRANCH_REVIEW_2026-10.md).

## Import scrolling: reproduced and fixed

Root cause: `app-workspace` owns `100dvh` and clips overflow; its route child is
shrunk by the shared flex rule. Unlike other long pages, `.imports-page` did not
own vertical scrolling. Its wide table's horizontal scroll container cannot make
the entire route scroll. The lower history was clipped and ordinary wheel input
could not reach row30. This is unrelated to import transaction processing.

Adopted the designer's route-level `overflow-y:auto; overscroll-behavior-y:contain`.
The table retains horizontal scrolling. There is no body scroll lock or fixed
position workaround. Chrome regression fails before and passes after using only
`page.mouse.wheel`, then checks the last row intersects the viewport and route
scrollTop exceeds500. It repeats after Settings→Imports navigation.

## Actual verification

| Check | Actual result | Evidence |
| --- | --- | --- |
| Wheel scroll,30 rows,1024×768/1280×800/1440×900/1920×1080,dark/light | PASS8/8 | `frontend/e2e/import-scroll.spec.ts`,8 screenshots |
| Existing Chrome regressions and workflows |14PASS,4 optional skips; compact navigation test initially failed because it expected the old always-visible phone sidebar | `frontend/e2e/{release,ui-fixes,workflows}.spec.ts` |
| Compact map/navigation after adapting test to the designer's menu button | PASS | Same production UI, test opens menu and checks it closes after navigation |
| Desktop visual matrix,7 pages,both themes,1280/1440 plus reduced map/sidebar | PASS | `docs/evidence/combined-v1.1/ui/matrix.json` and PNGs |
| TypeScript/Vite | PASS | `npm run build` |
| Lint |0errors,10warnings | `npm run lint`; existing effect warnings retained, no warning suppression |
| Native Yandex / physical touchpad | NOT TESTED | Native input/browser unavailable in this environment |

The screenshot matrix initially encountered an artifact-directory collision when
two independent Playwright processes shared the default output folder. The
isolated rerun with `--output=test-results/combined-visual` passed. No application
change or retry setting was used to hide that harness failure.

Screenshots contain isolated synthetic QA data. No credentials/cookies/traces
are committed. The old gas output, chart/history, notification polling, requests,
report date handling, opaque filters and native map wheel behavior remain intact.
Viewport tests do not establish native browser zoom/touchpad acceptance.

## Дополнительный импорт и новые карточки

В этом же проходе подтверждена гонка загрузок истории импорта: старый ответ мог
перекрыть результат refresh после завершения upload. Добавлен счётчик поколений
запроса и cleanup при уходе; только последний load меняет состояние. Refresh
показывает loading и не допускает повторного нажатия. Сообщения получили
доступные роли status/alert. Негативный тест ждёт фактическое завершение старого
HTTP500 и следующий animation frame; ошибка старого запроса не появляется.

Свежий focused suite:13PASS (10import wheel/loading/error/race и3scenario
dark/light/unavailable). Новые карточки получают реальные recorded scores
поставленных моделей на синтетических входах; raw JSON не показывается.
Реальный browser flow отдельно подтвердил scenario→review→draft→new.
Основной Chrome suite на новом изолированном cloud:26PASS/5optional skips;
после него отдельно gas→draft и mock alarm→sensor2PASS.
Семантика газового названия уточнена до общего газового порога1%: проверенный
bundle не задаёт отдельного химического контракта H₂/CH4, математика не менялась.

Нативный Яндекс, физический touchpad и настоящие browser zoom125/150% остаются
ручной проверкой. Их не подменяем CSS zoom/device-scale-factor.

## Заключительная проверка навигации

`frontend/e2e/designer-navigation.spec.ts`: Chrome155.0.8059.84, Windows,
19.10.2026 — **1PASS**, повторно на текущем cloud UI. Проверены object/channel
URL, закрытие, Back/Forward, reload, переход к объекту из компактной панели,
возврат фокуса по Escape и закрытие меню при расширении viewport.
Это реальный браузерный тест; Yandex/физический touchpad не проверены.

## Выявленная CI-гонка самого visual test

Run39274329802 на7c4b1cc: backend/frontend/combined-runtime PASS,
containers остановился на typography test (26PASS/8skips/1failure). Однократное
чтение fontSize временной строки таблицы вернуло пустое значение/NaN при смене
loading→data. Тест теперь исключает colspan-placeholder и повторно получает
актуальную ячейку до прежней проверки >=14px; ограничение не ослаблено.
Локально5повторов в2workers PASS, build PASS, lint0errors/10warnings.
Новый navigation test в этом CI прошёл. Полезные тесты не отключались.
См. `evidence/combined-v1.1/ci-typography-race.json`; новый tip получает отдельный CI.
