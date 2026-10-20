# Final product evidence — 20 October 2026

Functional source: release/final-rc 0f8d287014680b631603bc8c066fb9aa5739b320.
CI run39476724732: all4 jobs successful. The earlier e5c342d CI log confirms161 backend tests.

## Actual scope

- local-real-data-map.json: native Chrome155, genuine persisted results on a restored public DB,8 cases/34 screenshots, zero page/server errors. Local RC, not public deployment.
- remote-api-existing-build.json:5 roles, anonymous401, forbidden403, CSRF, Secure/HttpOnly/SameSiteStrict, logout401, HTTPS and d01901 on actual public ccd0620.
- remote-scenario-flow.json: genuine new public scenario run2,2SF/1Fire, requests13/14, draft/draft/new history and repeat idempotency, both themes/3 widths.
- remote-browser-existing-build.json: public ccd0620 primary flows, manual request15, one labelled synthetic observation import + duplicate, PDF/XLSX, refresh/Back, themes/sidebar. Notification entity NOT TESTED because no existing notice.
- source-freeze.json: model/runtime/math paths unchanged. New inference uses existing frozen models, not fabricated outputs.
- gas-history-proof.json: canonical3870 input rows match original generator checksum. Five later labelled demo observations were present when measured; the subsequent public smoke adds one further observation outside model cutoff.
- pre-model/ and post-model/: checksummed backups restored only into NEW isolated DBs, d01901/schema/API smoke. Public DB never restored over or cleaned.
- railway-blocker.json: real provider build outage; failed attempt93b6686e had no build. Existing public214fc396 continues to serveccd0620. Restarting an already-built finite scenario job succeeded, independently of the blocked web release.
- screenshots/: selected genuine screenshots; local-/public- prefixes identify their actual source. Other screenshots remain private to avoid repository noise.

## Reproduction

Run tests/final_model_map.cjs with RUN_FINAL_MODEL_MAP=true, BASE_URL pointing to a fresh isolated restore, REMOTE_ACCESS_FILE outside Git and FINAL_MAP_OUTPUT outside Git. This probe is read-only and does not invoke inference.
Run tests/remote/browser.cjs only with explicit RUN_REMOTE_RC=true: it creates labelled demo data. Never run pytest fixtures or load tests against public Railway.
Existing import concurrency evidence is reused by exact source identity: ../visual-integration-2026-10-20/imports and docs/IMPORT_VISUAL_SUPPLEMENT_2026-10-20.md.

Physical touchpad, native Yandex and native browser125/150% remain manual checks. Continuous workers/offsite backup and customer AD/integrations remain external dependencies. A local screenshot does not prove a new public build.
