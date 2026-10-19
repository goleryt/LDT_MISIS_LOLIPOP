# UI responsive review — 19 October 2026

Branch: `codex/designer-ui-fixes`. UI changes only; backend, model artifacts,
scoring, thresholds, integration policy and deployment are unchanged.

## Changes

- Import content owns vertical scrolling; the full history is reachable.
- Up to 800px: labeled modal navigation with close, Escape, focus wrapping and
  focus return. Resizing across the breakpoint closes the mobile menu.
- Up to 900px: object and sensor drawers become sequential panels. Object/channel
  URLs survive reload and Back/Forward; status-based sensor selection updates its URL.
- Phone forecasts use cards, retain the original proxy scores and windows, and
  focus the selected forecast details. Status labels are Russian; forecast times use Moscow.
- Settings use the available phone width below the shared header, while desktop
  centering remains independent of collapsed navigation.

## Verification

- TypeScript and Vite production build: passed. Lint: zero errors, ten warnings.
- Browser checks used local read-only synthetic API fixtures, not the live database.
- Settings, forecast cards and sensor panels fit at 320, 390, 430 and 768px.
- Import wheel scrolling reached the last of 18 fixture rows on desktop and phone.
- Menu Escape/focus wrapping, resize reset, forecast-detail focus, map reload and
  Back/Forward were checked. Desktop settings center remained x=720 at 1440px.
- Both themes were inspected. Physical-phone touch, Safari and production deployment
  were not exercised in this check. Viewport emulation does not establish those results.

## Existing concurrent-upload behavior (unchanged)

Admin/dispatcher uploads feed one shared database. Different files have separate
import records and may process concurrently. The same bytes and import type are
locked while processing; an already completed duplicate is recognized on retry.
Normalized duplicate event rows are skipped. Successful data and completion status
commit together; invalid file data rolls back.

The history is shared, newest import ID first, limited to 100 records. It shows
filename/type/status/counts/times, without an uploader column. Other sessions see
changes after refreshing; the importing session refreshes after its own success.
The page counters summarize those loaded history records. Uploads do not create
private datasets or trigger inference; forecasts remain shared results of the
separate ML job. Incompatible files using the same object/channel IDs are therefore
not isolated from each other. Three simultaneous real-server uploads were not
load-tested during this UI-only review.
