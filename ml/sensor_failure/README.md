# Leakage-safe channel-level proxy baseline

This directory builds a daily channel panel and can compare a rule baseline,
regularised logistic regression, CatBoost, and LightGBM for an
**observable-state proxy**. It does not predict or establish confirmed physical
sensor failure.

## Target assumptions

The default `target_failure_state_onset_24h` is defined at the end of an observed channel-day `t` with a formal 24-hour lead and a 24-hour outcome window. With daily cutoffs, features end at the close of day `t`, day `t+1` is the lead period, and the target is observed on day `t+2`.

- A channel is eligible only when its last observed state at `t` is outside the configurable failure-state dictionary.
- The label is `1` when a selected state occurs in `[cutoff + 24h, cutoff + 48h)`.
- The label is `0` only when that future channel-day contains at least one registered event and none is a selected state.
- The label is null when the next day is absent for that channel, when the horizon is beyond the delivered data, or when the channel is already in the selected state at cutoff.

This conservative observation rule deliberately avoids turning silence, global gaps, channel retirement, and a censored end-of-file horizon into negative examples. It uses registration time (`дата` + `время`), not proven physical-occurrence time. The default dictionary contains `Неисправен` and `Обесточен` only as candidate observable technical states. Confirmed incident or repair data is still required before any physical-failure claim.

`target_alarm_onset_24h` is implemented as a separately named comparator. It uses the same censoring rule but defines the state from `тревожное`; it must not be presented as a physical-failure target.

## Reproducible workflow

Install the local dependencies in a functioning Python environment, then run:

```powershell
python ml/sensor_failure/train_baseline.py --data-dir data/excel_utf8 --output-dir data/ml_sensor_failure_local
```

For this checkout, the project-local `.venv` uses Python 3.12.14. Recreate the
same development environment with:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r ml\sensor_failure\requirements-dev.txt
```

The configuration-driven entry point is preferred for recorded experiments:

```powershell
python ml/sensor_failure/run_experiment.py --config ml/sensor_failure/config/experiment.default.yaml --data-dir data/excel_utf8 --output-dir data/ml_sensor_failure_local
```

The default configuration leaves 2026 H1 locked. Final evaluation requires both `evaluation.evaluate_test: true` and the explicit `--unlock-test` flag.

The output directory is intentionally under `data/` and ignored by Git. Raw data is read only. The script writes a panel manifest, aggregate leakage audit, metrics, and local model artifacts; do not commit them.

By default, training uses 2019-2020 and 2022-2024, excluding the documented
2021 migration regime. It calibrates/chooses operational thresholds on 2025.
The configuration runner keeps 2026 H1 locked unless both the configuration and
the command explicitly unlock it. Add `--include-2021` for a training
sensitivity run; in that variant, 2021 is deliberately omitted from evaluation
because it is no longer out-of-sample. The `--latency-minutes 5 60 360 1440`
option applies an availability embargo before each cutoff and reruns the same
split, making reliance on late registrations visible.

## Leakage controls

- Every derived feature is computed from events at or before `d_cutoff_time`; no `d_future_*`, target, raw identifiers, or future state columns are accepted by model training.
- Target construction is performed after daily aggregation and uses an explicit next-day join, never a random row split.
- `ид_события`, `ид_канала_данных`, `тег_инженерной_системы`, and `название_датчика` are excluded from model features. The first is non-unique; the remaining identifiers are high-cardinality and do not safely generalise.
- The panel exposes `d_gap_days_since_previous` and `d_future_observed`; unobserved horizons stay null.
- Channel-to-object enrichment uses the supplied current catalogue as structural context only. Its snapshot semantics are not assumed to be historical truth.

The report includes PR-AUC, threshold precision/recall, false alerts per 1,000 eligible channel-days, Brier score, expected calibration error, and date-block bootstrap intervals. Accuracy is deliberately not reported as the primary metric.

## Kaggle development notebooks

The standalone notebooks in `notebooks/kaggle/` use a private, de-identified
panel rather than the raw 313.5M-event archive. Build the ignored upload folder
once with:

```powershell
python ml/sensor_failure/prepare_kaggle_package.py --data-dir data/excel_utf8 --output-dir data/kaggle_private_panel_v2
```

The package excludes 2026 rows and raw channel/object identifiers. It contains
source and builder checksums, a schema-versioned manifest, and stable
pseudonymous grouping keys. The notebooks use 2025 H1 only for calibration and
threshold selection and report headline development metrics on 2025 H2.

Runtime assignment:

- rule: CPU, teammate;
- LightGBM: CPU, teammate;
- logistic regression: CPU, project owner;
- CatBoost: Kaggle NVIDIA GPU, project owner.

Russian upload and handoff instructions are in
`docs/KAGGLE_RUNBOOK_RU.md`. The 2026 period was previously inspected and must
not be described as an untouched final test.

### Missing-target workstream

Notebook 07 builds a second, schema-versioned private dataset from the same
panel. It contains object-day and channel-element rows for observable access
and fire corroboration proxies plus a temporary channel-dropout proxy. It does
not invent confirmed incident labels.

- Codex owns notebooks 07, 10, 11 and 12.
- Claude owns notebooks 08 and 09 under
  `docs/CLAUDE_DELEGATION_NOTEBOOKS_08_09_RU.md`.
- Notebook 07 must run first; 08--11 consume its output. Notebook 10 now runs
  a CPU three-direction synthetic challenge despite its historical `_gpu`
  filename. Notebook 11 rebuilds its proxy labels and evaluates the full
  day-D-eligible cohort under `dropout-selection-3.0`.
- Notebook 12 requires 08, 09 and the corrected 11; the new 10 results are
  optional and appear as `not_evaluated` until attached. Old `results_10.zip`
  and `results_11_v2.zip` must not be used as final evidence.
- Scores from different targets are typed and never averaged.
- Backend replay uses `predict_dropout_bundle` and
  `predict_scenario_bundle` with canonical historical features, verified model
  checksums, and explicit E1/E4 semantics. See `docs/REPRODUCE_10_12_RU.md`.

The frozen implementation order and post-Claude corrections are documented in
`docs/ML_IMPLEMENTATION_SEQUENCE_RU.md`.
