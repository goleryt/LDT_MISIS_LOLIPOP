# Review of the team UI branch — 19 October 2026

Source: `origin/codex/designer-ui-fixes`, tip `f4e06d7bcf81d921212b686407b9ee1d452b7d84`.
Merge base / reviewed RC: `14aad86414826c59857cbc2766d10f48a0b43ba4`.
Source commits by nikita-kholev: `6d4035f` (alignment/disclosure) and
`f4e06d7` (import scrolling/responsive workflows). Both commits are descendants
of the RC; there is no divergent merge conflict. No merge or branch rewrite was used.

The complete diff contains 12 files, 488 insertions and 253 deletions. No backend,
dependencies, gas model, thresholds, native wheel handler or request workflow changes.

| Class | Files/change | Decision |
| --- | --- | --- |
| A | `designer-polish.css`, `EventJournalPage.tsx`, import control classes | Adopt disclosure arrows, select alignment and control spacing, retaining opaque RC surfaces and typography. |
| A | `responsive-polish.css`: import overflow | Adopt. The RC constrains the workspace to the viewport but Imports lacked its own vertical scroll owner. User wheel reproduction fails before and passes after. |
| B | `AppLayout.tsx`, `useMediaQuery.ts`, `ui-layout.css` | Adopt coordinated compact navigation, including close/Escape/resize and focus handling. Existing desktop sidebar tokens and native map zoom remain. |
| B | `MapPage.tsx`, responsive panel rules | Adopt object/channel URL synchronization and sequential compact drawers. Retain the existing SVG map and non-passive finite/clamped zoom handling. Verify Back/reload and desktop controls. |
| B | `PredictionsPage.tsx`, compact forecast cards | Adopt Russian status names, Moscow time, finite score formatting and compact focus handling. These gas-only cards do not establish support for new scenario models; scenario UI is a separate integration block. |
| C/D | `SettingsPage.tsx` portal and `settings.css` fixed overlay | Reject. At desktop widths above 1000px the proposed fixed panel starts at x=0 with z-index900 and can cover the navigation. It also escapes `.app-shell` theme/focus rules. Keep the RC scrollable workspace-relative settings. |
| C | Source `UI_RESPONSIVE_REVIEW_2026-10-19.md` | Do not import its PASS claims as our own evidence. Retain source attribution here; run our own acceptance checks. |

Selected files were copied from the reviewed source revision, not blindly merged.
The integration commit records the original author as co-author and references both
source commits. Main and the designer branch remain unchanged.

Before/after: `docs/evidence/combined-v1.1/ui/`. The pre-fix Chrome test using
`page.mouse.wheel` cannot reach row30 at1024×768; no `scrollIntoView` is used.
The regression repeats at1024×768,1280×800,1440×900,1920×1080 in both themes,
then navigates to Settings and back to detect persistent scroll locks.

Viewport emulation and synthetic wheel events do not prove physical touchpad or
native Yandex Browser behavior. Those remain separate manual checks.
