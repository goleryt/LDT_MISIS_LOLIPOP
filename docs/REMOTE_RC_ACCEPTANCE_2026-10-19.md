# Remote RC acceptance — 19.10.2026, Europe/Moscow

Branch: `release/final-rc`. Verified application/test source:
`ee16251a78a00dd496f848e64d9cce9ef12651e9` (includes both CI test fixes).
No main merge, final tag, history rewrite, model changes, or remote inference was performed.

This is the recorded functional run. Its subsequent documentation/evidence commit does
not change application code. Final publication is checked again against the branch HEAD;
the deployed SHA is available through admin `/api/v1/operations/status`, and the final
CI result through GitHub Actions. A commit cannot embed its own SHA or later run ID.

## Publication and data preservation

- [Live demo](https://ldt-demo-production.up.railway.app/).
- Railway project `d4c500cc-fab0-4f7f-ad7e-a52db7a5585c`, environment
  `1dd4e231-b7ab-48b3-879e-b17389d1e911`, existing service `ldt-demo`.
- Successful deployment `25be6357-bcd7-4281-a249-7e37ffb95eae`:
  [deployment](https://railway.com/project/d4c500cc-fab0-4f7f-ad7e-a52db7a5585c/service/40ca29d5-bf32-4a43-bcd9-c03d05b27b9f?id=25be6357-bcd7-4281-a249-7e37ffb95eae).
  Runtime reports exactly `ee16251a78a00dd496f848e64d9cce9ef12651e9`.
- Uploaded tracked-only `git archive HEAD`, cloud Dockerfile, pre-deploy
  `alembic upgrade head`, `/ready` gate. Existing PostgreSQL 18 and its volume retained.
- Before upgrade: `c92601`, 173863 events, 3 predictions, 4 imports, 0 requests.
  Additive migrations to `d01602`; immediately after upgrade counts unchanged.
- Pre-upgrade custom-format dump: 9885817 bytes; remote/local SHA-256 both
  `1dddb28a3dff8f62c389cfab713e71eb84ee99649ef6abc34bd951ed3a78f3ae`.
  Off-host copy retained outside Git. No restore over the remote database was performed.
- Validation adds one explicitly labelled demo import/event, four demo requests,
  three separately provisioned role accounts, and one labelled notification pointing to
  an **existing historical factual alarm**. Existing account passwords are unchanged.
  The notification is an administrative validation record, not proof of an active source worker.
- Free trial credit was available; no paid subscription or tariff change was enabled.
  Continued free availability is subject to the account's remaining credit/trial.

## Actual CI

[Validate service, run 39173000415](https://github.com/goleryt/LDT_MISIS_LOLIPOP/actions/runs/39173000415)
at `ee16251`: **PASS**, all backend/frontend/containers jobs successful.
[Machine-readable jobs and steps](evidence/release-rc/remote/github-ci.json).
Actual log totals: backend **109 PASS**, 4 warnings; frontend lint **0 errors / 10 warnings**,
build PASS; primary CI Chrome **12 PASS / 7 opt-in or data-dependent skips**, then frozen
bundle-to-draft Chrome **1 PASS**. [Concise totals](evidence/release-rc/remote/ci-summary.json).

Two preceding failures were test-harness defects, not hidden application failures:

1. `b7e1bc9`, run 39160279378: typography test assumed import history already existed.
   Commit `33dc317` supplies a typed visual registry fixture, independent of execution order.
   The real upload/duplicate test remains enabled.
2. `33dc317`, run 39161554737: unqualified `getByRole('status')` matched successful save
   and concurrently loading history. Commit `ee16251` scopes success feedback and adds
   delayed-history regression coverage. No test was disabled.

Local focused checks: typography 1 PASS; saved prediction/draft 2 PASS; tsc/Vite PASS;
lint 0 errors / 10 existing warnings. The existing CI additionally tests the unchanged
frozen bundle contract on isolated labelled synthetic inputs; it does not run against Railway.

## Requirement matrix

| Requirement | Status | Implementation / verification | Actual result / evidence | Known limitation |
|---|---|---|---|---|
| Exact RC deployment | PASS | cloud image, APP_COMMIT, SSH settings, operations | SHA verified; [runtime](evidence/release-rc/remote/runtime.json), [deployment](evidence/release-rc/remote/railway-deployment.json) | CLI upload, no GitHub autodeploy configured |
| Migrations / data preservation | PASS | backup first; pre-deploy upgrade; `alembic current` | `d01602`; original counts preserved; [backup](evidence/release-rc/remote/pre-migration-backup.json) | No destructive downgrade or remote restore |
| Public HTTPS / health / readiness | PASS | verified TLS HTTP client and native Chrome | root/health/ready 200, HTTP redirects to HTTPS, TLS1.3 | Certificate expiry is recorded, not a perpetual guarantee |
| Auth / security | PASS | actual login/me/logout, direct REST, expired own QA session | 401/403, CSRF, Secure/HttpOnly/SameSite=strict; [API](evidence/release-rc/remote/api-security.json) | Corporate AD remains external |
| Five-role backend enforcement | PASS | manager, dispatcher, technician, admin, analyst | Allowed operations 200, forbidden writes/admin/imports 403; [requests](evidence/release-rc/remote/request-security-regression.json) | Integrator machine token not reprovisioned remotely |
| Map → object → sensor → history | PASS | actual Chrome, stored data, URL refresh | Exact sensor and history visible; [browser](evidence/release-rc/remote/browser.json) | Conditional coordinates remain explicitly labelled |
| Alarm → exact sensor | PASS | click existing actual alarm row | Correct objectId/channelId and sensor history | Historical demo observations, not a live customer feed |
| Notification → entity / personal read | PASS | labelled existing-alarm notice, browser click, REST read twice | Correct navigation, persisted read, other user still unread; [notifications](evidence/release-rc/remote/notifications.json) | Notification setup was administrative; source worker absent |
| Prediction → decision → recommendation → draft → review → confirm | PASS | existing prediction 1, actual browser | Request 3: draft → draft(save) → new → in_progress → completed | Existing stale shadow result; no new inference |
| Filled manual request / concurrency | PASS | browser visible fields + direct REST | Request 4 created, fresh edit 200, stale edit 409; repeated prediction link creates no duplicate | Ordinary manual request starts new |
| Safe import → registry / duplicate | PASS | one normal row on existing synthetic demo channel | Import 5 completed; repeated file recognised; original journal retained | Remote JSON only; other formats covered by isolated CI/local matrix |
| PDF / XLSX | PASS | browser downloads + populated September report | Cyrillic, generated date/source; 2-page PDF, XLSX31 rows; [reports](evidence/release-rc/remote/reports.json) | No industrial-size remote export load |
| Correct CSS / user UI fixes | PASS | remote CSS matches local RC SHA256, screenshots | [asset identity](evidence/release-rc/remote/frontend-build-identity.json), 21 PNGs; readable themes and ≥14px table cells | Finite desktop sample; not every browser scale |
| Resize / zoom / object overlay | PASS | 1440×900,1280×800,1024×700; wheel/buttons; synthetic pinch | Finite scale, visible controls/close, unchanged drawer width | Physical touchpad not exercised |
| Settings / sidebar | PASS | overlay position comparison, icon bounds, screenshots | No settings jump; aligned toggle; noninteractive logo | No global redesign |
| Chrome remote | PASS | Windows11, native Chrome155.0.8059.84 via Playwright | 14 recorded checks, zero pageerrors / unexpected API5xx | No claim of a human physical-device run |
| Native Yandex Browser | NOT TESTED | standard executable paths and App Paths checked again | Browser absent | MANUAL ACTION REQUIRED |
| Physical touchpad | NOT TESTED | synthetic wheel/pinch automated PASS | No physical input available | MANUAL TOUCHPAD VERIFICATION REQUIRED |
| Integration worker | PARTIAL | actual services/processes and heartbeat inspection | No deployed worker, empty source cursors, not_observed | Existing five-source mock evidence is local/CI only |
| ML scheduler | PARTIAL | actual services / heartbeat / job history | No running scheduler; last job remains September29 | Intentionally not launched for validation; ML frozen |
| Automatic remote backup | PARTIAL | existing services / operations | not_configured; manual pre-upgrade dump+off-host checksum PASS | Persistent backup service/offsite rotation not deployed |
| Remote performance | PASS | five serial read-only timing samples | 274.4–392.5ms, all 200; API evidence | Not load/SLA or comparable hardware to local baseline |
| Pre-merge analysis | PASS | merge-tree without commit; diff/secret/file checks | No conflicts with origin/main; main untouched | Does not authorize a merge |

## Evidence and manual actions

Evidence directory: [remote](evidence/release-rc/remote/). Browser probe:
[tests/remote/README](../tests/remote/README.md). No cookies, passwords, database URL,
private keys, browser traces, raw backups or QA databases are committed.
Full file inventory from the initial `b7e1bc9`:
[changed-files](evidence/release-rc/remote/changed-files.txt).
Trailing whitespace in 13 historical evidence text files was normalized for the requested
full branch diff check; their result values and provenance were not changed or rerun.

Manual: native Yandex Browser and physical touchpad using
[browser checklist](BROWSER_ACCEPTANCE_RC.md), on the public URL and exact deployed commit.
Operational: deploy/configure background integration and persistent/offsite backups before
claiming continuous operation; approved scheduler inputs/marker and customer infrastructure
are separate. Do not enable production mocks or invent a customer endpoint.

Missing final materials: current presentation PPTX/PDF and accompanying DOCX/PDF.
No final tag has been created. Main merge requires the owner's separate instruction.
