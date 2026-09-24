# ML-specific operating rules

These rules extend the repository-level `AGENTS.md` for work under `ml/`.

## Experiment gate

- Before training, write the hypothesis, target/proxy meaning, data unit, temporal split, primary metric, acceptance threshold, and expected decision.
- Change one material factor per experiment. Record the configuration and result compactly so failed ideas are not rerun.
- EDA/data tasks may inspect targets, leakage, coverage, and distributions, but must not start model training unless the user explicitly moves the work to model building.

## Run budget

- Use the sequence: static checks -> synthetic contract tests -> small representative sample -> cached panel -> full archive. Advance only when the previous stage passes and the next stage is necessary.
- Never rebuild a full panel or retrain unchanged models if an artifact manifest matches source checksums, preprocessing version, target definition, split, and configuration.
- Prefer one bounded baseline run over broad grid search. Add experiments only when they test a named hypothesis likely to change the decision.
- Reuse one validated canonical panel across comparable models. Do not rescan the 313M-row archive separately for every estimator or reporting change.
- Default to memory-bounded CPU workflows. GPU or cloud runs require a concrete expected benefit and compatible hardware/runtime.

## Evaluation discipline

- Keep registration time, feature-availability time, target time, and delayed-arrival assumptions distinct.
- Use temporal/out-of-time validation; never use random row splits for headline results.
- Report user-visible alert episodes and operational burden in addition to row-level metrics. Do not inflate results through repeated recalculation of the same alert.
- Report selected-category coverage and per-module results; do not hide a weak module inside an overall average.
- Treat proxy labels as proxies. Do not call them confirmed physical failures or incidents without authoritative labels.

## Output discipline

- Keep progress output aggregate-only: rows, dates, target balance, coverage, leakage checks, runtime, and metrics. Do not stream per-row logs.
- During long runs, update only on completion, failure, a material phase transition, or required user action.
- Store generated data and models only in ignored local paths; never commit raw data or sensitive artifacts.
