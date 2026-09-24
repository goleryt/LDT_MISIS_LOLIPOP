# Project operating rules

## Token-efficient work

- Start from the current request, `git status`, and the smallest relevant files. Do not inventory the whole repository unless the task genuinely requires it.
- Use `rg` and targeted line ranges. Avoid recursive directory dumps, full notebook JSON, full logs, large diffs, and rereading unchanged documents.
- Reuse confirmed facts from the current task and existing project reports. Refresh a fact only when its source, branch, data, or requirement changed.
- Batch independent read-only checks when this reduces round trips, but cap output and return aggregates rather than raw records.
- Keep commentary to meaningful milestones: material finding, decision, blocker, requested approval, or completion. Do not send repetitive “still running” updates.
- Final responses should lead with the outcome and include only decisions, important evidence, risks, changed files, and the next necessary action.

## Scope and execution

- Prefer the smallest check that can answer the question: syntax/static check, focused test, synthetic fixture, sample, then full run only when needed.
- Do not repeat an expensive command when a valid artifact or result already exists. Verify its source/config/code identity first.
- Before a long or resource-heavy run, state its purpose and expected output. If the user mentions a low token/usage budget, pause nonessential work and finish only the minimum requested verification.
- Stop immediately when the user asks to pause or stop. Do not launch a final check after that request.
- Preserve unrelated and uncommitted work. Never switch branches, merge, clean, or rewrite files merely to inspect them.

## Evidence discipline

- Separate confirmed source facts, expert answers, repository observations, and inference. Do not promote participant speculation to a project requirement.
- Preserve exact Russian dataset column names. Use aggregate, de-identified diagnostics and never print secrets or large raw-data samples.
- When reviewing branches, refresh remote refs once, then compare commits/diffs directly. Do not repeatedly fetch unchanged state.
- Report uncertainty explicitly. Do not spend tokens trying to manufacture certainty that the supplied data or organizers do not provide.

## Verification

- Match verification effort to risk. Run focused tests for changed behavior; do not run the entire suite by habit.
- Capture concise failure evidence once, diagnose it, and avoid retry loops that do not change the conditions.
- Token efficiency must not remove essential safety, leakage, data-contract, migration, or correctness checks.

