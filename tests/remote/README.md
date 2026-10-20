# Explicit remote demo smoke

`browser.cjs` uses installed Google Chrome through `frontend/node_modules/@playwright/test`.
It runs only with `RUN_REMOTE_RC=true`, against the existing Railway demo over verified
HTTPS. It does not run inference, reset data, change configuration, or record traces.

The probe creates labelled demo requests, processes an existing prediction recommendation,
and imports one normal observation into its existing synthetic demo channel. Run only on
this approved demonstration dataset. Do not reuse it against a customer database. Existing
requests are never removed or unlinked; a new draft requires an eligible stored result.

Set `REMOTE_ACCESS_FILE` to an absolute JSON file **outside the repository**, containing
`dispatcher` and `manager` objects with `username` and `password`. Provision accounts through
the documented administrator workflow. Never commit that file. The release validation also
checks admin/technician/analyst directly through REST; those results are in the evidence.

From the repository root, after `npm ci` in frontend:

```powershell
$env:RUN_REMOTE_RC='true'
$env:REMOTE_ACCESS_FILE='C:/private/rc-access.json'
$env:REMOTE_EVIDENCE_DIR='C:/private/remote-validation'
node tests/remote/browser.cjs
```

Output: aggregate `browser.json`, screenshots, and factual PDF/XLSX exports. The file never
prints credentials, saves storage state, or enables browser traces. Review output before
adding evidence. Physical touchpad and native Yandex Browser remain separate manual checks.

Recorded successful run: [remote acceptance](../../docs/REMOTE_RC_ACCEPTANCE_2026-10-19.md).
