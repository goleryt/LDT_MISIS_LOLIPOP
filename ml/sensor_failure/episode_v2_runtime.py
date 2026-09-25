"""Эксперимент 13: строгая onset-цель v2 и причинные cadence-признаки (CPU).

Опирается на pre2025_audit_runtime (ноутбук 05): preflight, фолды, метрики, эпизоды,
бутстрэп и модели берутся оттуда без изменений, чтобы результаты были сопоставимы.
План и гипотезы: docs/EXPERIMENT_13_EPISODE_V2_RU.md.
"""

from __future__ import annotations

import gc
import json
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

try:
    from pre2025_audit_runtime import (  # noqa: F401
        CATEGORICAL_FEATURES, EVENT_COLUMN, FOLDS, LOAD_END_EXCLUSIVE, NUMERIC_FEATURES, RECURRENCE,
        REQUIRED_PANEL_COLUMNS, STRESS_YEAR, TARGET, APPrep, Bootstrap, ContractError, EvalFrame,
        LightGBMModel, LogisticModel, ReproductionError, _as_date_expr, _clean, _json_default,
        apply_platt, assert_safe_features, calibrate_and_threshold, ci, environment_info, episodes,
        evaluate_scores, log, make_config, preflight, public, recurrence_score, rule_score, sample_training,
    )
except ImportError:  # в notebook модуль 05 выполняется ячейкой выше
    pass


TARGET_CODE_V2 = "failure_state_strict_onset_Dplus2_proxy_v2"
TARGET_MEANING_V2 = (
    "Наблюдаемый proxy начала эпизода Неисправен/Обесточен ровно в сутки D+2: в D и D+1 "
    "failure-state не наблюдался. Признаки — до конца D. Не подтверждённая физическая поломка."
)
CALENDAR = ["d_month", "d_weekday"]
BASE_NO_CALENDAR = [f for f in NUMERIC_FEATURES if f not in CALENDAR]
CADENCE_WINDOWS = (7, 30)
CADENCE_FEATURES = [
    f"d_cad_{name}_{w}d"
    for w in CADENCE_WINDOWS
    for name in ("active_days", "event_sum", "alarm_sum", "failure_event_sum", "failure_days")
] + ["d_cad_gap_median_30d", "d_cad_gap_ratio_30d", "d_cad_observed_age_days"]
FEATURE_SETS = {
    "v2_base": BASE_NO_CALENDAR,
    "v2_cadence": BASE_NO_CALENDAR + CADENCE_FEATURES,
    "v2_cadence_no_recurrence": [f for f in BASE_NO_CALENDAR if f not in RECURRENCE] + CADENCE_FEATURES,
}
REFERENCE = "v2_base"
CANDIDATES = ["v2_cadence", "v2_cadence_no_recurrence"]
BASELINES_V2 = ["B0_constant", "B1_type_prevalence", "B2_recurrence", "B3_rule", "B4_logistic"]


# ---------------------------------------------------------------------------
# 1. Загрузка всех строк до 2025 (включая неразмеченные: они нужны истории и правилу D+1)
# ---------------------------------------------------------------------------
def load_all_pre2025(data_path: Path, mode: str, smoke_share: int) -> Any:
    import polars as pl

    lazy = pl.scan_parquet(data_path)
    schema = lazy.collect_schema()
    columns = sorted(REQUIRED_PANEL_COLUMNS - {"target_alarm_onset_24h", "d_future_alarm_event_date"})
    exprs = [(_as_date_expr(pl, c, schema[c]).alias(c) if c in (
        "d_cutoff_date", "d_target_start_date", "d_target_end_date_exclusive", EVENT_COLUMN) else pl.col(c))
        for c in columns]
    frame = lazy.select(exprs).filter(pl.col("d_cutoff_date") < pl.lit(LOAD_END_EXCLUSIVE))
    if mode == "SMOKE":
        frame = frame.filter(pl.col("d_channel_key").hash(seed=20260921) % smoke_share == 0)
    frame = frame.collect().with_columns(
        pl.col(TARGET).cast(pl.Int8),
        *[pl.col(c).cast(pl.String) for c in CATEGORICAL_FEATURES],
    ).sort(["d_channel_key", "d_cutoff_date"])
    if frame.is_empty():
        raise ContractError("После фильтра до 2025 года не осталось строк")
    if frame["d_cutoff_date"].max() >= LOAD_END_EXCLUSIVE:
        raise ContractError("В память попали строки 2025 года")
    return frame


# ---------------------------------------------------------------------------
# 2. Цель v2 и cadence-признаки
# ---------------------------------------------------------------------------
def add_v2_target(frame: Any) -> tuple[Any, dict[str, Any]]:
    """Метка v2: v1, кроме строк, где у канала в D+1 наблюдалось failure-событие (тогда null)."""
    import polars as pl

    next_day = frame.select(
        "d_channel_key",
        (pl.col("d_cutoff_date") - pl.duration(days=1)).alias("d_cutoff_date"),
        (pl.col("d_failure_state_event_count_24h").cast(pl.Float64).fill_null(0) > 0).alias("_dplus1_failure"),
    )
    out = frame.join(next_day, on=["d_channel_key", "d_cutoff_date"], how="left").with_columns(
        pl.col("_dplus1_failure").fill_null(False)  # нет строки D+1 => событий не было, состояние не менялось
    ).with_columns(
        pl.when(pl.col(TARGET).is_null()).then(None)
        .when(pl.col("_dplus1_failure")).then(None)
        .otherwise(pl.col(TARGET)).cast(pl.Int8).alias("target_v2")
    )
    labelled = out.filter(pl.col(TARGET).is_not_null())
    audit = {
        "v1_labelled_rows": labelled.height,
        "v1_positive_rows": int(labelled[TARGET].sum()),
        "excluded_dplus1_failure_rows": int(labelled["_dplus1_failure"].sum()),
        "excluded_dplus1_failure_v1_positives": int(labelled.filter(pl.col("_dplus1_failure"))[TARGET].sum()),
        "v2_labelled_rows": int(out["target_v2"].is_not_null().sum()),
        "v2_positive_rows": int(out["target_v2"].sum() or 0),
    }
    audit["share_of_v1_positives_started_on_dplus1"] = (
        audit["excluded_dplus1_failure_v1_positives"] / audit["v1_positive_rows"] if audit["v1_positive_rows"] else None)
    return out.drop("_dplus1_failure"), audit


def add_cadence_features(frame: Any) -> Any:
    """Окна по строкам канала с датой в (D−w, D]. Пропуски не достраиваются."""
    import polars as pl

    base = frame.sort(["d_channel_key", "d_cutoff_date"]).with_columns(
        pl.lit(1.0).alias("_one"),
        pl.col("d_event_count_24h").cast(pl.Float64).fill_null(0).alias("_ev"),
        pl.col("d_alarm_count_24h").cast(pl.Float64).fill_null(0).alias("_al"),
        pl.col("d_failure_state_event_count_24h").cast(pl.Float64).fill_null(0).alias("_fs"),
        (pl.col("d_failure_state_event_count_24h").cast(pl.Float64).fill_null(0) > 0).cast(pl.Float64).alias("_fd"),
        pl.col("d_gap_days_since_previous").cast(pl.Float64).alias("_gap"),
    )
    exprs = []
    for w in CADENCE_WINDOWS:
        for name, col in (("active_days", "_one"), ("event_sum", "_ev"), ("alarm_sum", "_al"),
                          ("failure_event_sum", "_fs"), ("failure_days", "_fd")):
            exprs.append(pl.col(col).rolling_sum_by("d_cutoff_date", window_size=f"{w}d", closed="right")
                         .over("d_channel_key").cast(pl.Float32).alias(f"d_cad_{name}_{w}d"))
    exprs.append(pl.col("_gap").rolling_median_by("d_cutoff_date", window_size="30d", closed="right")
                 .over("d_channel_key").cast(pl.Float32).alias("d_cad_gap_median_30d"))
    exprs.append((pl.col("d_cutoff_date") - pl.col("d_cutoff_date").min().over("d_channel_key"))
                 .dt.total_days().cast(pl.Float32).alias("d_cad_observed_age_days"))
    out = base.with_columns(exprs).with_columns(
        (pl.col("_gap") / pl.col("d_cad_gap_median_30d").clip(lower_bound=1.0)).cast(pl.Float32).alias("d_cad_gap_ratio_30d"))
    return out.drop(["_one", "_ev", "_al", "_fs", "_fd", "_gap"])


# ---------------------------------------------------------------------------
# 3. Прогон
# ---------------------------------------------------------------------------
def _fold_frames(frame: Any, fold: dict[str, Any], target_col: str) -> tuple[Any, Any, Any]:
    import polars as pl

    lab = frame.filter(pl.col(target_col).is_not_null()).with_columns(pl.col(target_col).alias(TARGET))
    train = lab.filter(pl.col("d_year").is_in(fold["train_years"])
                       & (pl.col("d_target_end_date_exclusive") <= pl.lit(fold["train_end"])))
    def between(a, b):
        return lab.filter((pl.col("d_target_start_date") >= pl.lit(a)) & (pl.col("d_target_end_date_exclusive") <= pl.lit(b))
                          & (pl.col("d_year") != STRESS_YEAR))
    return train, between(*fold["calibration"]), between(*fold["validation"])


def run_episode_v2(config: dict[str, Any]) -> dict[str, Any]:
    import polars as pl

    started = time.perf_counter()
    mode = config["mode"]
    out_dir = Path(os.environ.get("LDT_OUTPUT_DIR", config["output_dir"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "status": None, "mode": mode, "experiment": "13_failure_onset_v2_cadence",
        "comparability": "non_comparable" if mode == "SMOKE" else "comparable_within_this_run",
        "target_code": TARGET_CODE_V2, "target_semantics_ru": TARGET_MEANING_V2,
        "evaluation_scope": "pre-2025 rolling folds (development validation, not a final test)",
        "plan": "docs/EXPERIMENT_13_EPISODE_V2_RU.md",
        "config": {k: v for k, v in config.items() if k != "output_dir"},
        "environment": environment_info(),
        "feature_sets": FEATURE_SETS,
    }
    keys: set[str] = set()
    try:
        data_path, manifest, checks = preflight(mode)
        frame = load_all_pre2025(data_path, mode, int(config["smoke_channel_share"]))
    except ContractError as error:
        result.update(status="contract_failed", stop_reason=str(error))
        return finish_v2(result, out_dir, started, keys)
    result["panel"] = {"schema_version": manifest.get("panel_schema_version"), "data_sha256": manifest.get("data_sha256"),
                       "contract_checks": checks, "rows_loaded_pre2025_all": frame.height}
    keys = {str(k) for k in frame["d_channel_key"].unique()} | {str(k) for k in frame["d_object_key"].unique()}
    frame, target_audit = add_v2_target(frame)
    frame = add_cadence_features(frame)
    result["target_audit"] = target_audit
    for name, feats in FEATURE_SETS.items():
        assert_safe_features(feats + list(CATEGORICAL_FEATURES))
    ratio, seed, min_pos = int(config["negative_to_positive_ratio"]), int(config["random_seed"]), int(config["min_positives_for_pr_auc"])
    folds_out, store = {}, {}
    try:
        for fold in FOLDS:
            name = fold["name"]
            log(f"=== {name} ===")
            fold_out: dict[str, Any] = {"models": {}}
            # E1 (описательно): v1 на тех же признаках без календаря
            tr1, ca1, va1 = _fold_frames(frame, fold, TARGET)
            m1 = LightGBMModel(BASE_NO_CALENDAR, list(CATEGORICAL_FEATURES), config).fit(sample_training(tr1, ratio, seed))
            platt1, thr1 = calibrate_and_threshold(m1.raw(ca1), ca1[TARGET].to_numpy().astype(np.int8), config)
            ev1 = EvalFrame(va1, fold["validation"][0])
            e1 = evaluate_scores("v1_base", ev1, apply_platt(platt1, m1.raw(va1)), thr1, 0.0, config, full=False)
            e1.pop("_primary")
            fold_out["v1_reference"] = {"rows": va1.height, "positives": int(ev1.y.sum()), **e1,
                                        "note_ru": "цель v1, другие строки; прямое сравнение с v2 некорректно"}
            del m1
            # v2
            train, cal, val = _fold_frames(frame, fold, "target_v2")
            if train.is_empty() or cal.is_empty() or val.is_empty():
                raise ContractError(f"{name}: пустая выборка v2")
            y_cal = cal[TARGET].to_numpy().astype(np.int8)
            pre = pl.concat([train, cal], how="vertical_relaxed")
            b0 = float(pre[TARGET].mean())
            ev = EvalFrame(val, fold["validation"][0])
            fold_out["rows"] = {"train": train.height, "calibration": cal.height, "validation": val.height}
            fold_out["positives"] = {"train": int(train[TARGET].sum()), "calibration": int(y_cal.sum()), "validation": int(ev.y.sum())}
            preds, prim, thr = {}, {}, {}

            def register(model_name: str, p: np.ndarray, t: float) -> None:
                assert len(p) == val.height
                evaluation = evaluate_scores(model_name, ev, p, t, b0, config, full=True)
                prim[model_name] = evaluation.pop("_primary")
                preds[model_name], thr[model_name] = p, t
                fold_out["models"][model_name] = evaluation

            _, t0 = calibrate_and_threshold(np.full(cal.height, b0), y_cal, config, calibrate=False)
            register("B0_constant", np.full(val.height, b0), t0)
            stats = pre.group_by("тип_датчика").agg(pl.len().alias("n"), pl.col(TARGET).mean().alias("r"))
            rate = {r["тип_датчика"]: r["r"] for r in stats.iter_rows(named=True) if r["n"] >= config["b1_min_type_rows"] and r["тип_датчика"] is not None}
            b1 = lambda f: np.array([rate.get(v, b0) for v in f["тип_датчика"].to_list()], float)  # noqa: E731
            _, t1 = calibrate_and_threshold(b1(cal), y_cal, config, calibrate=False)
            register("B1_type_prevalence", b1(val), t1)
            for bname, scorer in (("B2_recurrence", recurrence_score), ("B3_rule", rule_score)):
                pl_, t_ = calibrate_and_threshold(scorer(cal), y_cal, config)
                register(bname, apply_platt(pl_, scorer(val)), t_)
            sampled = sample_training(train, ratio, seed)
            logit = LogisticModel(BASE_NO_CALENDAR, list(CATEGORICAL_FEATURES), config).fit(sampled)
            pl_, t_ = calibrate_and_threshold(logit.raw(cal), y_cal, config)
            register("B4_logistic", apply_platt(pl_, logit.raw(val)), t_)
            importances = {}
            for model_name, feats in FEATURE_SETS.items():
                try:
                    model = LightGBMModel(feats, list(CATEGORICAL_FEATURES), config).fit(sampled)
                    raw_cal = model.raw(cal)
                    if not np.isfinite(raw_cal).all():
                        raise ValueError("нечисловые скоры на calibration")
                    pl_, t_ = calibrate_and_threshold(raw_cal, y_cal, config)
                    register(model_name, apply_platt(pl_, model.raw(val)), t_)
                    importances[model_name] = model.importance()
                except Exception as error:
                    raise ReproductionError(f"{name}: {model_name} не обучился: {type(error).__name__}: {error}") from error
                del model
            fold_out["feature_importance_gain_share"] = {"interpretation_ru": "predictive association, не причинность",
                                                         "models": importances}
            seen = set(pre["d_channel_key"].unique().to_list())
            seen_row = np.array([c in seen for c in val["d_channel_key"].to_list()])
            groups = {"seen_channel": seen_row, "unseen_channel": ~seen_row}
            code_masks = {}
            for g, mask in groups.items():
                cm = np.zeros(ev.n_channels, bool)
                cm[ev.channel[mask]] = True
                code_masks[g] = cm
            fold_out["support"] = {}
            for model_name, p in preds.items():
                entry = {}
                for g, mask in groups.items():
                    item = episodes(ev, p, thr[model_name], int(config["alert_budget_per_day"]), int(config["cooldown_hours"]), row_mask=mask)
                    yy = ev.y[mask]
                    from sklearn.metrics import average_precision_score
                    entry[g] = {"rows": int(mask.sum()), "positives": int(yy.sum()),
                                "pr_auc": float(average_precision_score(yy, p[mask])) if yy.sum() >= min_pos and yy.sum() < len(yy) else None,
                                "episode_recall_50_72h": item["recall"], "proxy_events": item["proxy_events"]}
                fold_out["support"][model_name] = entry
            folds_out[name] = fold_out
            store[name] = {"ev": ev, "preds": preds, "prim": prim, "code_masks": code_masks, "groups": groups}
            gc.collect()
    except (ReproductionError, ContractError) as error:
        result.update(status="stopped", stop_reason=str(error), folds=folds_out)
        return finish_v2(result, out_dir, started, keys)
    result["folds"] = folds_out
    select_v2(result, store, config)
    result["status"] = "completed" if mode == "FULL" else "completed_smoke_non_comparable"
    return finish_v2(result, out_dir, started, keys)


def select_v2(result: dict[str, Any], store: dict[str, Any], config: dict[str, Any]) -> None:
    folds = result["folds"]
    names = list(next(iter(folds.values()))["models"])
    key = f"budget_{config['alert_budget_per_day']}_cooldown_{config['cooldown_hours']}h"
    min_pos = int(config["min_positives_for_pr_auc"])

    def mean(n: str, get) -> float | None:
        vals = [get(folds[f]["models"][n]) for f in folds]
        vals = [v for v in vals if v is not None]
        return float(np.mean(vals)) if vals else None

    pooled = {n: {"pr_auc": mean(n, lambda m: m["point"]["pr_auc"]),
                  "episode_recall": mean(n, lambda m: m["episodes"][key]["recall"]),
                  "episode_precision": mean(n, lambda m: m["episodes"][key]["precision"]),
                  "false_alerts_per_1000": mean(n, lambda m: m["point"]["false_alerts_per_1000_eligible_channel_days"]),
                  "brier": mean(n, lambda m: m["point"]["brier_score"])} for n in names}
    result["pooled_mean_over_folds"] = pooled
    boot = Bootstrap({f: s["ev"].n_weeks for f, s in store.items()}, int(config["bootstrap_reps"]), int(config["bootstrap_seed"]))
    preps: dict[tuple[str, str], APPrep] = {}

    def paired(cand: str, ref: str, group: str | None = None) -> dict[str, Any]:
        out, acc = {"difference": f"{cand} - {ref}"}, {"pr_auc": [], "episode_recall_50_72h": [], "episode_precision_50_72h": []}
        for f, s in store.items():
            for n in (cand, ref):
                preps.setdefault((f, n), APPrep(s["ev"].y, s["preds"][n]))
            mask = None if group is None else s["groups"][group]
            cmask = None if group is None else s["code_masks"][group]
            a, b = boot.pr_auc(f, s["ev"], preps[(f, cand)], mask), boot.pr_auc(f, s["ev"], preps[(f, ref)], mask)
            pa, ra = boot.episode(f, s["prim"][cand], cmask)
            pb, rb = boot.episode(f, s["prim"][ref], cmask)
            per = {"pr_auc": a - b, "episode_recall_50_72h": ra - rb, "episode_precision_50_72h": pa - pb}
            out[f] = {k: ci(v) for k, v in per.items()}
            for k, v in per.items():
                acc[k].append(v)
        with np.errstate(all="ignore"):
            out["mean_over_folds"] = {k: ci(np.nanmean(np.stack(v), axis=0)) for k, v in acc.items()}
        return out

    strongest = max(("B2_recurrence", "B3_rule", "B4_logistic"), key=lambda b: pooled[b]["pr_auc"] or -1)
    comps = {f"{c}_vs_{REFERENCE}": paired(c, REFERENCE) for c in CANDIDATES}
    comps["v2_cadence_no_recurrence_vs_v2_cadence"] = paired("v2_cadence_no_recurrence", "v2_cadence")
    for n in [REFERENCE] + CANDIDATES:
        comps[f"{n}_vs_strongest_baseline"] = paired(n, strongest)
    for b in ("B2_recurrence", "B3_rule", "B4_logistic"):
        if b != strongest:  # сравнение с сильнейшим уже есть выше
            comps[f"{REFERENCE}_vs_{b}"] = paired(REFERENCE, b)
    result["paired_bootstrap"] = {"method": "парный бутстрэп блоками календарных недель validation",
                                  "reps": int(config["bootstrap_reps"]), "seed": int(config["bootstrap_seed"]),
                                  "strongest_baseline": strongest, "comparisons": comps}

    def unseen(n: str, k: str) -> float | None:
        vals = [folds[f]["support"][n]["unseen_channel"][k] for f in folds]
        vals = [v for v in vals if v is not None]
        return float(np.mean(vals)) if vals else None

    unseen_events = sum(folds[f]["support"][REFERENCE]["unseen_channel"]["proxy_events"] for f in folds)
    ref = pooled[REFERENCE]
    ref_beats_baselines = (comps[f"{REFERENCE}_vs_strongest_baseline"]["mean_over_folds"]["pr_auc"]["ci95_low"] or -1) > 0
    selection: dict[str, Any] = {"reference": REFERENCE, "reference_beats_strongest_baseline_pr_auc": ref_beats_baselines,
                                 "candidates": {}}
    passed = []
    for c in CANDIDATES:
        cp = pooled[c]
        cm = comps[f"{c}_vs_{REFERENCE}"]["mean_over_folds"]
        g = {
            "g1_primary_ci95_above_zero": bool((cm["episode_recall_50_72h"]["ci95_low"] or -1) > 0),
            "g2_episode_precision_not_worse_by_0.01": bool((cp["episode_precision"] or 0) >= (ref["episode_precision"] or 0) - 0.01),
            "g3_false_alerts_within_limit": bool((cp["false_alerts_per_1000"] or 0) <= (ref["false_alerts_per_1000"] or 0) + max(1.0, 0.05 * (ref["false_alerts_per_1000"] or 0))),
            "g5_beats_strongest_baseline_pr_auc": bool((comps[f"{c}_vs_strongest_baseline"]["mean_over_folds"]["pr_auc"]["ci95_low"] or -1) > 0),
        }
        if unseen_events < min_pos or unseen(c, "pr_auc") is None or unseen(REFERENCE, "pr_auc") is None:
            g["g4_unseen_not_worse_by_0.01"] = "insufficient_support"
        else:
            g["g4_unseen_not_worse_by_0.01"] = bool(unseen(c, "pr_auc") >= unseen(REFERENCE, "pr_auc") - 0.01
                                                   and unseen(c, "episode_recall_50_72h") >= unseen(REFERENCE, "episode_recall_50_72h") - 0.01)
        ok = all(v is True or v == "insufficient_support" for v in g.values())
        selection["candidates"][c] = {"gates": g, "passed": ok, "failed": [k for k, v in g.items() if v is False]}
        if ok:
            passed.append(c)
    if passed:
        best = max(passed, key=lambda c: (pooled[c]["episode_recall"], pooled[c]["episode_precision"]))
        selection.update(selected=best, reason="passed_all_gates_vs_v2_base")
    elif ref_beats_baselines:
        selection.update(selected=REFERENCE, reason="no_candidate_passed_gates_keep_v2_base")
    else:
        selection.update(selected=strongest, reason="v2_base_does_not_beat_strongest_baseline_keep_baseline")
    result["selection"] = selection

    def decide(entry: dict[str, Any], metric: str) -> dict[str, str]:
        c = entry["mean_over_folds"][metric]
        if c["ci95_low"] is None:
            return {"decision": "inconclusive", "reason": "NO_FINITE_BOOTSTRAP"}
        if c["ci95_low"] > 0:
            return {"decision": "confirmed", "reason": "CI95_ABOVE_ZERO"}
        if c["ci95_high"] < 0:
            return {"decision": "rejected", "reason": "CI95_BELOW_ZERO"}
        return {"decision": "inconclusive", "reason": "CI95_INCLUDES_ZERO"}

    def replaces(entry: dict[str, Any], tol: float = 0.01) -> dict[str, str]:
        c = entry["mean_over_folds"]["pr_auc"]
        if c["ci95_low"] is None:
            return {"decision": "inconclusive", "reason": "NO_FINITE_BOOTSTRAP"}
        if c["ci95_low"] > -tol:
            return {"decision": "confirmed", "reason": "LOSS_WITHOUT_RECURRENCE_BOUNDED_BY_0.01_AT_CI95"}
        if c["ci95_high"] < 0:
            return {"decision": "rejected", "reason": "SIGNIFICANT_LOSS_WITHOUT_RECURRENCE"}
        return {"decision": "inconclusive", "reason": "CI95_ALLOWS_LOSS_ABOVE_0.01"}

    ta = result["target_audit"]
    v2_support = all(folds[f]["positives"]["validation"] >= min_pos for f in folds)
    result["hypotheses"] = {
        "E1_v2_target_has_support": {"decision": "confirmed" if v2_support else "rejected",
                                     "reason": "GE_MIN_POSITIVES_EACH_FOLD" if v2_support else "LT_MIN_POSITIVES_IN_A_FOLD",
                                     "share_of_v1_positives_started_on_dplus1": ta["share_of_v1_positives_started_on_dplus1"]},
        "E1_v2_base_beats_strongest_baseline_pr_auc": decide(comps[f"{REFERENCE}_vs_strongest_baseline"], "pr_auc"),
        "E2_cadence_improves_primary": decide(comps[f"v2_cadence_vs_{REFERENCE}"], "episode_recall_50_72h"),
        "E2_cadence_improves_pr_auc": decide(comps[f"v2_cadence_vs_{REFERENCE}"], "pr_auc"),
        "E3_cadence_replaces_recurrence": replaces(comps["v2_cadence_no_recurrence_vs_v2_cadence"]),
    }


def finish_v2(result: dict[str, Any], out_dir: Path, started: float, keys: set[str]) -> dict[str, Any]:
    result["runtime_seconds"] = round(time.perf_counter() - started, 1)
    result = _clean(result)
    text = json.dumps(result, ensure_ascii=False, indent=2, default=_json_default)
    leaked = {k for k in keys if len(k) >= 8} & set(re.findall(r"[A-Za-z0-9_\-]+", text))
    if leaked:
        raise RuntimeError(f"В результатах обнаружены идентификаторы ({len(leaked)}) — запись остановлена")
    (out_dir / "results_failure_onset_v2.json").write_text(text, encoding="utf-8")
    (out_dir / "summary_failure_onset_v2_ru.md").write_text(render_v2(result), encoding="utf-8")
    log("Записано: results_failure_onset_v2.json, summary_failure_onset_v2_ru.md")
    return result


def _fmt(v: Any, d: int = 4) -> str:
    if v is None:
        return "—"
    if isinstance(v, int):
        return f"{v:,}".replace(",", " ")
    return f"{float(v):.{d}f}"


def _ci_s(c: dict[str, Any] | None) -> str:
    if not c or c.get("ci95_low") is None:
        return "—"
    return f"{c['mean_difference']:+.4f} [{c['ci95_low']:+.4f}; {c['ci95_high']:+.4f}]"


def render_v2(r: dict[str, Any]) -> str:
    L = ["# Эксперимент 13: строгая onset-цель v2 и cadence-признаки", "",
         f"Статус: **{r.get('status')}** · режим **{r.get('mode')}** · `{r.get('comparability')}`", "",
         f"Цель `{r['target_code']}`: {r['target_semantics_ru']}", "",
         "План и гипотезы зафиксированы до обучения: `docs/EXPERIMENT_13_EPISODE_V2_RU.md`. "
         "Оценка — pre-2025 rolling-фолды (development validation), не финальный тест.", ""]
    if r.get("mode") == "SMOKE":
        L += ["> **SMOKE**: подвыборка каналов и деревьев; числа несравнимы.", ""]
    if r.get("status") not in ("completed", "completed_smoke_non_comparable"):
        L += ["## Остановка", "", f"Причина: {r.get('stop_reason')}", ""]
        return "\n".join(L) + "\n"
    ta = r["target_audit"]
    L += ["## Цель v2 против v1", "",
          f"- v1: размеченных строк {_fmt(ta['v1_labelled_rows'])}, positives {_fmt(ta['v1_positive_rows'])};",
          f"- исключено правилом D+1: строк {_fmt(ta['excluded_dplus1_failure_rows'])}, из них v1-positives "
          f"{_fmt(ta['excluded_dplus1_failure_v1_positives'])} (**{_fmt(ta['share_of_v1_positives_started_on_dplus1'], 3)}** "
          "доли v1-positives — эпизод начался в D+1, а не в D+2);",
          f"- v2: размеченных строк {_fmt(ta['v2_labelled_rows'])}, positives {_fmt(ta['v2_positive_rows'])}.", ""]
    budget = r["config"]["alert_budget_per_day"]; cd = r["config"]["cooldown_hours"]
    L += [f"## Модели на цели v2 (среднее по фолдам; эпизоды {budget} каналов/сутки, cooldown {cd} ч)", "",
          "| модель | PR-AUC | episode recall | episode precision | ложных / 1000 | Brier |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for n, p in r["pooled_mean_over_folds"].items():
        L.append(f"| `{n}` | {_fmt(p['pr_auc'])} | {_fmt(p['episode_recall'])} | {_fmt(p['episode_precision'])} | {_fmt(p['false_alerts_per_1000'], 1)} | {_fmt(p['brier'])} |")
    L += ["", "Для справки — LightGBM без календаря на цели v1 (другие строки, прямо не сравнивается):", ""]
    for f, v in r["folds"].items():
        ref = v["v1_reference"]
        L.append(f"- {f}: PR-AUC {_fmt(ref['point']['pr_auc'])}, positives {_fmt(ref['positives'])}.")
    L += ["", "## Парные 95% CI", "", "| сравнение | Δ PR-AUC | Δ episode recall | Δ episode precision |", "| --- | ---: | ---: | ---: |"]
    for c in r["paired_bootstrap"]["comparisons"].values():
        m = c["mean_over_folds"]
        L.append(f"| {c['difference']} | {_ci_s(m['pr_auc'])} | {_ci_s(m['episode_recall_50_72h'])} | {_ci_s(m['episode_precision_50_72h'])} |")
    L += ["", "## Гипотезы", "", "| гипотеза | решение | причина |", "| --- | --- | --- |"]
    for k, h in r["hypotheses"].items():
        L.append(f"| `{k}` | **{h['decision']}** | `{h['reason']}` |")
    s = r["selection"]
    L += ["", "## Отбор", "", "| кандидат | прошёл | не пройдены |", "| --- | --- | --- |"]
    for c, v in s["candidates"].items():
        L.append(f"| `{c}` | {'да' if v['passed'] else 'нет'} | {', '.join(v['failed']) or '—'} |")
    L += ["", f"**Выбрано: `{s['selected']}`** (`{s['reason']}`). Сильнейший baseline: `{r['paired_bootstrap']['strongest_baseline']}`.", "",
          "## Ограничения", "",
          "- Proxy-цель по журналу, не подтверждённые поломки. Правило D+1 опирается на `d_failure_state_event_count_24h`.",
          "- Два pre-2025 фолда; 2025 H2 и 2026 не использовались.",
          "- Тихие сутки не достраивались; строки без метки не считаются отрицательными.", "",
          f"Время прогона: {r.get('runtime_seconds')} с."]
    return "\n".join(L) + "\n"


def make_config_v2(mode: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    config = make_config(mode)
    config.update({"alert_budget_per_day": 50, "cooldown_hours": 72})  # основная метрика плана
    config.update(overrides or {})
    return config


# ---------------------------------------------------------------------------
# 4. Самопроверки
# ---------------------------------------------------------------------------
def run_v2_self_tests() -> dict[str, bool]:
    import polars as pl

    d = lambda k: date(2024, 1, 1) + timedelta(days=k)  # noqa: E731
    rows = []
    # канал A: D=0 чисто, D+1 failure, D+2 failure -> v1=1, v2=null; D=3 чисто, D+1 нет строки, D+2 failure -> v2=1
    for k, fs, tgt in ((0, 0, 1), (1, 2, None), (2, 1, None), (3, 0, 1), (5, 1, None), (9, 0, 0)):
        rows.append({"d_channel_key": "chA", "d_cutoff_date": d(k), "d_failure_state_event_count_24h": float(fs),
                     TARGET: tgt, "d_event_count_24h": 1.0, "d_alarm_count_24h": 0.0, "d_gap_days_since_previous": None})
    frame = pl.DataFrame(rows, schema_overrides={TARGET: pl.Int8})
    out, audit = add_v2_target(frame)
    v2 = dict(zip(out["d_cutoff_date"].to_list(), out["target_v2"].to_list()))
    assert v2[d(0)] is None and v2[d(3)] == 1 and v2[d(9)] == 0, v2
    assert audit["excluded_dplus1_failure_v1_positives"] == 1
    # причинность cadence: изменение будущих строк не меняет признаки прошлых
    base = add_cadence_features(out)
    changed = add_cadence_features(out.with_columns(
        pl.when(pl.col("d_cutoff_date") >= d(5)).then(99.0).otherwise(pl.col("d_event_count_24h")).alias("d_event_count_24h")))
    early = base["d_cutoff_date"] < d(5)
    assert np.allclose(base.filter(early)["d_cad_event_sum_7d"].to_numpy(), changed.filter(early)["d_cad_event_sum_7d"].to_numpy())
    # пропущенные сутки не считаются: в окне 7д на D=9 только строки 3,5,9
    row9 = base.filter(pl.col("d_cutoff_date") == d(9))
    assert row9["d_cad_active_days_7d"].item() == 3.0, row9["d_cad_active_days_7d"].item()
    assert row9["d_cad_failure_days_7d"].item() == 1.0
    return {"v2_excludes_dplus1_failure": True, "v2_keeps_strict_onset_after_silent_dplus1": True,
            "cadence_is_causal": True, "cadence_counts_only_observed_days": True}
