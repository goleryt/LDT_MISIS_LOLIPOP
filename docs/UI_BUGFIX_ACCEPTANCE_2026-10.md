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
| Lint |0errors,9warnings | `npm run lint`; effect warnings retained, no warning suppression |
| Native Yandex / physical touchpad | NOT TESTED | Native input/browser unavailable in this environment |

The screenshot matrix initially encountered an artifact-directory collision when
two independent Playwright processes shared the default output folder. The
isolated rerun with `--output=test-results/combined-visual` passed. No application
change or retry setting was used to hide that harness failure.

Screenshots contain isolated synthetic QA data. No credentials/cookies/traces
are committed. The old gas output, chart/history, notification polling, requests,
report date handling, opaque filters and native map wheel behavior remain intact.
Viewport tests do not establish native browser zoom/touchpad acceptance.
