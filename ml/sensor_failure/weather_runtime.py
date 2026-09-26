"""Эксперимент 05W: погода Москвы как признак прогноза отказов (раздел 9 ноутбука 05, CPU).

Опирается на pre2025_audit_runtime (ноутбук 05): preflight, загрузка, фолды, семплирование, модели, метрики,
эпизоды и бутстрэп берутся оттуда без изменений, поэтому M0 воспроизводит основной прогон.
План и гипотезы: docs/EXPERIMENT_05W_WEATHER_RU.md. Данные погоды: weather_data.py (Open-Meteo, CC BY 4.0).
"""

from __future__ import annotations

import gc
import io
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
        CALENDAR, CATEGORICAL_FEATURES, FOLDS, NUMERIC_FEATURES, TARGET, APPrep, Bootstrap, ContractError,
        EvalFrame, LightGBMModel, LogisticModel, ReproductionError, _clean, _frame_between, _json_default,
        apply_platt, assert_safe_features, calibrate_and_threshold, ci, environment_info, episodes,
        evaluate_scores, load_pre2025, log, make_config, preflight, recurrence_score, rule_score, sample_training,
    )
    from weather_data import WEATHER_CSV_SHA256, WEATHER_SOURCE, weather_csv_bytes  # noqa: F401
except ImportError:  # в notebook модули выполняются ячейками выше
    pass


RAW_WEATHER_COLUMNS = [
    "temperature_2m_mean", "temperature_2m_min", "temperature_2m_max", "precipitation_sum", "rain_sum",
    "snowfall_sum", "precipitation_hours", "wind_speed_10m_max", "wind_gusts_10m_max",
]
W_OBS = [
    "w_t_mean_d0", "w_t_min_d0", "w_t_max_d0", "w_precip_d0", "w_snow_d0", "w_precip_hours_d0", "w_gust_max_d0",
    "w_precip_3d", "w_precip_7d", "w_snow_7d", "w_t_mean_7d", "w_dt_mean_1d", "w_freeze_thaw_7d", "w_gust_max_3d",
]
W_FCST = [
    "w_fc_t_min_2d", "w_fc_t_max_2d", "w_fc_t_mean_2d", "w_fc_precip_2d", "w_fc_snow_2d", "w_fc_gust_max_2d",
    "w_fc_freeze_thaw_2d", "w_fc_dt_mean_d2_vs_d0",
]
PLACEBO_SHIFT_DAYS = 364  # тот же день недели и сезон, другая погода
W_PLACEBO = ["wp" + f[1:] for f in W_OBS]
M0_NUMERIC = list(NUMERIC_FEATURES)
NO_CAL = [f for f in M0_NUMERIC if f not in CALENDAR]
MODELS = {  # имя -> числовые признаки (категориальные у всех как у M0)
    "M0_lightgbm": M0_NUMERIC,
    "W1_obs": M0_NUMERIC + W_OBS,
    "P1_obs_placebo": M0_NUMERIC + W_PLACEBO,
    "W2_obs_fcst_oracle": M0_NUMERIC + W_OBS + W_FCST,
    "NC_no_calendar": NO_CAL,
    "W3_no_calendar_obs": NO_CAL + W_OBS,
    "P3_no_calendar_placebo": NO_CAL + W_PLACEBO,
}
REFERENCE = "M0_lightgbm"
CANDIDATES = {"W1_obs": "P1_obs_placebo", "W3_no_calendar_obs": "P3_no_calendar_placebo"}  # кандидат -> плацебо
FULL_EVAL = {"M0_lightgbm", "W1_obs", "W2_obs_fcst_oracle", "W3_no_calendar_obs"}
# PR-AUC M0 из FULL-прогона 05 (research_results_pre2025.json, 2026-09-23) — проверка воспроизведения
M0_REFERENCE_PR_AUC = {"fold_2023": 0.5447934998065774, "fold_2024": 0.6160952895865183}
FOCUS_TYPES = ["Состояние насоса", "Состояние фазы", "Состояние вентилятора", "Датчик дыма"]


# ---------------------------------------------------------------------------
# 1. Погода и признаки
# ---------------------------------------------------------------------------
def load_weather(raw: bytes | None = None) -> Any:
    import polars as pl

    raw = weather_csv_bytes() if raw is None else raw
    frame = pl.read_csv(io.BytesIO(raw), try_parse_dates=True).with_columns(pl.col("date").cast(pl.Date))
    frame = frame.select(["date", *RAW_WEATHER_COLUMNS]).with_columns(
        [pl.col(c).cast(pl.Float64) for c in RAW_WEATHER_COLUMNS]).sort("date")
    days = (frame["date"].max() - frame["date"].min()).days + 1
    if days != frame.height or frame["date"].n_unique() != frame.height:
        raise ContractError("Ряд погоды должен быть непрерывным и без повторов")
    if frame.select(pl.any_horizontal(pl.col(RAW_WEATHER_COLUMNS).is_null())).to_series().any():
        raise ContractError("В погоде есть пропуски")
    return frame


def weather_features(weather: Any) -> Any:
    """Признаки на дату D (колонка d_cutoff_date). W_OBS — только сутки ≤ D; W_FCST — ровно D+1 и D+2."""
    import polars as pl

    tmean, tmin, tmax = pl.col("temperature_2m_mean"), pl.col("temperature_2m_min"), pl.col("temperature_2m_max")
    precip, snow, gust = pl.col("precipitation_sum"), pl.col("snowfall_sum"), pl.col("wind_gusts_10m_max")
    ft = ((tmin < 0) & (tmax > 0)).cast(pl.Float64)
    w = weather.with_columns(ft.alias("_ft"))
    obs = [
        tmean.alias("w_t_mean_d0"), tmin.alias("w_t_min_d0"), tmax.alias("w_t_max_d0"),
        precip.alias("w_precip_d0"), snow.alias("w_snow_d0"),
        pl.col("precipitation_hours").alias("w_precip_hours_d0"), gust.alias("w_gust_max_d0"),
        precip.rolling_sum(3).alias("w_precip_3d"), precip.rolling_sum(7).alias("w_precip_7d"),
        snow.rolling_sum(7).alias("w_snow_7d"), tmean.rolling_mean(7).alias("w_t_mean_7d"),
        (tmean - tmean.shift(1)).alias("w_dt_mean_1d"), pl.col("_ft").rolling_sum(7).alias("w_freeze_thaw_7d"),
        gust.rolling_max(3).alias("w_gust_max_3d"),
    ]
    n1, n2 = (lambda e: e.shift(-1)), (lambda e: e.shift(-2))
    fcst = [
        pl.min_horizontal(n1(tmin), n2(tmin)).alias("w_fc_t_min_2d"),
        pl.max_horizontal(n1(tmax), n2(tmax)).alias("w_fc_t_max_2d"),
        ((n1(tmean) + n2(tmean)) / 2).alias("w_fc_t_mean_2d"),
        (n1(precip) + n2(precip)).alias("w_fc_precip_2d"),
        (n1(snow) + n2(snow)).alias("w_fc_snow_2d"),
        pl.max_horizontal(n1(gust), n2(gust)).alias("w_fc_gust_max_2d"),
        (n1(pl.col("_ft")) + n2(pl.col("_ft"))).alias("w_fc_freeze_thaw_2d"),
        (n2(tmean) - tmean).alias("w_fc_dt_mean_d2_vs_d0"),
    ]
    out = w.select([pl.col("date").alias("d_cutoff_date"), *obs, *fcst])
    # min/max_horizontal пропускают null — в последних двух сутках ряда прогноза нет, обнуляем явно
    edge = pl.int_range(pl.len()) >= pl.len() - 2
    out = out.with_columns([pl.when(edge).then(None).otherwise(pl.col(c)).alias(c) for c in W_FCST])
    placebo = out.select([(pl.col("d_cutoff_date") - pl.duration(days=PLACEBO_SHIFT_DAYS)).alias("d_cutoff_date"),
                          *[pl.col(f).alias(p) for f, p in zip(W_OBS, W_PLACEBO)]])
    out = out.join(placebo, on="d_cutoff_date", how="left")
    return out.select(["d_cutoff_date", *W_OBS, *W_FCST, *W_PLACEBO]).with_columns(
        [pl.col(c).cast(pl.Float32) for c in W_OBS + W_FCST + W_PLACEBO])


def attach_weather(frame: Any, features: Any) -> tuple[Any, dict[str, Any]]:
    import polars as pl

    out = frame.join(features, on="d_cutoff_date", how="left").sort(["d_cutoff_date", "d_channel_key"])
    if out.height != frame.height:
        raise ContractError("Join погоды изменил число строк")
    audit = {c: float(out[c].is_null().mean()) for c in ("w_t_mean_d0", "w_precip_7d", "w_fc_t_mean_2d", "wp_t_mean_d0")}
    if audit["w_t_mean_d0"] > 0 or audit["w_fc_t_mean_2d"] > 0 or audit["wp_t_mean_d0"] > 0:
        raise ContractError(f"Погода покрывает не все даты панели: {audit}")
    dates = out["d_cutoff_date"]
    return out, {"null_share": audit, "panel_date_min": dates.min(), "panel_date_max": dates.max()}


# ---------------------------------------------------------------------------
# 2. Прогон
# ---------------------------------------------------------------------------
def run_weather(config: dict[str, Any]) -> dict[str, Any]:
    import polars as pl
    from sklearn.metrics import average_precision_score

    started = time.perf_counter()
    mode = config["mode"]
    out_dir = Path(os.environ.get("LDT_OUTPUT_DIR", config["output_dir"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "status": None, "mode": mode, "experiment": "05W_weather",
        "comparability": "non_comparable" if mode == "SMOKE" else "comparable_within_this_run",
        "target": TARGET,
        "target_semantics": "observable proxy: onset of Неисправен/Обесточен on D+2; not a confirmed physical failure",
        "evaluation_scope": "pre-2025 rolling folds (development validation, not a final test)",
        "plan": "docs/EXPERIMENT_05W_WEATHER_RU.md",
        "weather_source": {**WEATHER_SOURCE, "csv_sha256": WEATHER_CSV_SHA256},
        "feature_sets": {"W_obs": W_OBS, "W_fcst_oracle": W_FCST, "W_obs_placebo": W_PLACEBO,
                         "placebo_shift_days": PLACEBO_SHIFT_DAYS},
        "models": {k: {"numeric": v, "categorical": list(CATEGORICAL_FEATURES)} for k, v in MODELS.items()},
        "config": {k: v for k, v in config.items() if k != "output_dir"},
        "environment": environment_info(),
    }
    keys: set[str] = set()
    try:
        weather = weather_features(load_weather())
        data_path, manifest, checks = preflight(mode)
        frame = load_pre2025(data_path, mode, int(config["smoke_channel_share"]))
        keys = {str(k) for k in frame["d_channel_key"].unique()} | {str(k) for k in frame["d_object_key"].unique()}
        frame, join_audit = attach_weather(frame, weather)
    except ContractError as error:
        result.update(status="contract_failed", stop_reason=str(error))
        return finish_weather(result, out_dir, started, keys)
    result["panel"] = {"schema_version": manifest.get("panel_schema_version"), "data_sha256": manifest.get("data_sha256"),
                       "contract_checks": checks, "rows_labelled_pre2025": frame.height, "weather_join": join_audit}
    for feats in MODELS.values():
        assert_safe_features(feats + list(CATEGORICAL_FEATURES))
    ratio, seed, min_pos = int(config["negative_to_positive_ratio"]), int(config["random_seed"]), int(config["min_positives_for_pr_auc"])
    folds_out, store = {}, {}
    try:
        for fold in FOLDS:
            name = fold["name"]
            log(f"=== {name} ===")
            train = frame.filter(pl.col("d_year").is_in(fold["train_years"])
                                 & (pl.col("d_target_end_date_exclusive") <= pl.lit(fold["train_end"])))
            cal, val = _frame_between(frame, *fold["calibration"]), _frame_between(frame, *fold["validation"])
            if train.is_empty() or cal.is_empty() or val.is_empty():
                raise ContractError(f"{name}: пустая выборка")
            y_cal = cal[TARGET].to_numpy().astype(np.int8)
            pre = pl.concat([train, cal], how="vertical")
            b0 = float(pre[TARGET].mean())
            ev = EvalFrame(val, fold["validation"][0])
            fold_out: dict[str, Any] = {
                "rows": {"train": train.height, "calibration": cal.height, "validation": val.height},
                "positives": {"train": int(train[TARGET].sum()), "calibration": int(y_cal.sum()), "validation": int(ev.y.sum())},
                "models": {},
            }
            preds, prim, thr = {}, {}, {}

            def register(model_name: str, p: np.ndarray, t: float, full: bool) -> None:
                assert len(p) == val.height
                evaluation = evaluate_scores(model_name, ev, p, t, b0, config, full=full)
                prim[model_name] = evaluation.pop("_primary")
                preds[model_name], thr[model_name] = p, t
                fold_out["models"][model_name] = evaluation

            for bname, scorer in (("B2_recurrence", recurrence_score), ("B3_rule", rule_score)):
                pl_, t_ = calibrate_and_threshold(scorer(cal), y_cal, config)
                register(bname, apply_platt(pl_, scorer(val)), t_, False)
            sampled = sample_training(train, ratio, seed)  # те же строки, что в основном прогоне 05
            logit = LogisticModel(M0_NUMERIC, list(CATEGORICAL_FEATURES), config).fit(sampled)
            pl_, t_ = calibrate_and_threshold(logit.raw(cal), y_cal, config)
            register("B4_logistic", apply_platt(pl_, logit.raw(val)), t_, False)
            del logit
            importances = {}
            for model_name, feats in MODELS.items():
                try:
                    model = LightGBMModel(feats, list(CATEGORICAL_FEATURES), config).fit(sampled)
                    raw_cal = model.raw(cal)
                    if not np.isfinite(raw_cal).all():
                        raise ValueError("нечисловые скоры на calibration")
                    pl_, t_ = calibrate_and_threshold(raw_cal, y_cal, config)
                    register(model_name, apply_platt(pl_, model.raw(val)), t_, model_name in FULL_EVAL)
                    imp = model.importance()
                    wshare = sum(v for k, v in imp.items() if k.startswith(("w_", "wp_")))
                    importances[model_name] = {"weather_gain_share": wshare,
                                               "calendar_gain_share": sum(imp.get(c, 0.0) for c in CALENDAR),
                                               "top10": dict(sorted(imp.items(), key=lambda kv: -kv[1])[:10])}
                except Exception as error:
                    raise ReproductionError(f"{name}: {model_name} не обучился: {type(error).__name__}: {error}") from error
                del model
                gc.collect()
            fold_out["feature_importance_gain_share"] = {"interpretation_ru": "predictive association, не причинность",
                                                         "models": importances}
            ref_pr = M0_REFERENCE_PR_AUC.get(name)
            got = fold_out["models"][REFERENCE]["point"]["pr_auc"]
            fold_out["m0_reproduction"] = {"pr_auc_this_run": got, "pr_auc_notebook_05_full": ref_pr,
                                           "abs_difference": abs(got - ref_pr) if (mode == "FULL" and got is not None) else None,
                                           "matches_within_0.002": bool(mode == "FULL" and got is not None and abs(got - ref_pr) < 0.002)}
            seen = set(pre["d_channel_key"].unique().to_list())
            seen_row = np.array([c in seen for c in val["d_channel_key"].to_list()])
            groups = {"seen_channel": seen_row, "unseen_channel": ~seen_row}
            for t_name in FOCUS_TYPES:
                groups[f"type:{t_name}"] = ev.sensor == t_name
            code_masks = {}
            for g, mask in groups.items():
                cm = np.zeros(ev.n_channels, bool)
                cm[ev.channel[mask]] = True
                code_masks[g] = cm
            fold_out["support"] = {}
            for model_name in MODELS:
                p = preds[model_name]
                entry = {}
                for g in ("seen_channel", "unseen_channel"):
                    mask = groups[g]
                    item = episodes(ev, p, thr[model_name], int(config["alert_budget_per_day"]), int(config["cooldown_hours"]), row_mask=mask)
                    yy = ev.y[mask]
                    entry[g] = {"rows": int(mask.sum()), "positives": int(yy.sum()),
                                "pr_auc": float(average_precision_score(yy, p[mask])) if yy.sum() >= min_pos and yy.sum() < len(yy) else None,
                                "episode_recall_50_72h": item["recall"], "proxy_events": item["proxy_events"]}
                fold_out["support"][model_name] = entry
            folds_out[name] = fold_out
            store[name] = {"ev": ev, "preds": preds, "prim": prim, "code_masks": code_masks, "groups": groups}
            gc.collect()
    except (ReproductionError, ContractError) as error:
        result.update(status="stopped", stop_reason=str(error), folds=folds_out)
        return finish_weather(result, out_dir, started, keys)
    result["folds"] = folds_out
    select_weather(result, store, config)
    result["status"] = "completed" if mode == "FULL" else "completed_smoke_non_comparable"
    return finish_weather(result, out_dir, started, keys)


def select_weather(result: dict[str, Any], store: dict[str, Any], config: dict[str, Any]) -> None:
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
                  "brier": mean(n, lambda m: m["point"]["brier_score"]),
                  "ece": mean(n, lambda m: m["point"]["ece_10_bins"])} for n in names}
    result["pooled_mean_over_folds"] = pooled
    boot = Bootstrap({f: s["ev"].n_weeks for f, s in store.items()}, int(config["bootstrap_reps"]), int(config["bootstrap_seed"]))
    preps: dict[tuple[str, str], APPrep] = {}

    def paired(cand: str, ref: str, group: str | None = None) -> dict[str, Any]:
        out, acc = {"difference": f"{cand} - {ref}"}, {"pr_auc": [], "episode_recall_50_72h": [], "episode_precision_50_72h": []}
        for f, s in store.items():
            mask = None if group is None else s["groups"][group]
            if mask is not None and int(s["ev"].y[mask].sum()) < min_pos:
                out[f] = "insufficient_support"
                continue
            for n in (cand, ref):
                preps.setdefault((f, n), APPrep(s["ev"].y, s["preds"][n]))
            cmask = None if group is None else s["code_masks"][group]
            a, b = boot.pr_auc(f, s["ev"], preps[(f, cand)], mask), boot.pr_auc(f, s["ev"], preps[(f, ref)], mask)
            pa, ra = boot.episode(f, s["prim"][cand], cmask)
            pb, rb = boot.episode(f, s["prim"][ref], cmask)
            per = {"pr_auc": a - b, "episode_recall_50_72h": ra - rb, "episode_precision_50_72h": pa - pb}
            out[f] = {k: ci(v) for k, v in per.items()}
            for k, v in per.items():
                acc[k].append(v)
        if acc["pr_auc"]:
            with np.errstate(all="ignore"):
                out["mean_over_folds"] = {k: ci(np.nanmean(np.stack(v), axis=0)) for k, v in acc.items()}
            out["folds_used"] = len(acc["pr_auc"])
        return out

    strongest = max(("B2_recurrence", "B3_rule", "B4_logistic"), key=lambda b: pooled[b]["pr_auc"] or -1)
    comps = {
        "W1_obs_vs_M0": paired("W1_obs", REFERENCE),
        "W1_obs_vs_placebo": paired("W1_obs", "P1_obs_placebo"),
        "P1_placebo_vs_M0": paired("P1_obs_placebo", REFERENCE),
        "W2_fcst_oracle_vs_W1": paired("W2_obs_fcst_oracle", "W1_obs"),
        "W2_fcst_oracle_vs_M0": paired("W2_obs_fcst_oracle", REFERENCE),
        "NC_no_calendar_vs_M0": paired("NC_no_calendar", REFERENCE),
        "W3_no_calendar_obs_vs_M0": paired("W3_no_calendar_obs", REFERENCE),
        "W3_no_calendar_obs_vs_NC": paired("W3_no_calendar_obs", "NC_no_calendar"),
        "W3_no_calendar_obs_vs_placebo": paired("W3_no_calendar_obs", "P3_no_calendar_placebo"),
    }
    for n in (REFERENCE, *CANDIDATES):
        comps[f"{n}_vs_strongest_baseline"] = paired(n, strongest)
    by_type = {}
    for t_name in FOCUS_TYPES:
        g = f"type:{t_name}"
        by_type[t_name] = {"W1_obs_vs_M0": paired("W1_obs", REFERENCE, g),
                           "W1_obs_vs_placebo": paired("W1_obs", "P1_obs_placebo", g),
                           "W2_fcst_oracle_vs_M0": paired("W2_obs_fcst_oracle", REFERENCE, g)}
    result["paired_bootstrap"] = {"method": "парный бутстрэп блоками календарных недель validation",
                                  "reps": int(config["bootstrap_reps"]), "seed": int(config["bootstrap_seed"]),
                                  "strongest_baseline": strongest, "comparisons": comps,
                                  "by_sensor_type_descriptive": by_type}

    def unseen(n: str, k: str) -> float | None:
        vals = [folds[f]["support"][n]["unseen_channel"][k] for f in folds]
        vals = [v for v in vals if v is not None]
        return float(np.mean(vals)) if vals else None

    def low(entry: dict[str, Any], metric: str) -> float:
        m = entry.get("mean_over_folds", {}).get(metric, {})
        return m.get("ci95_low") if m.get("ci95_low") is not None else -1.0

    unseen_events = sum(folds[f]["support"][REFERENCE]["unseen_channel"]["proxy_events"] for f in folds)
    ref = pooled[REFERENCE]
    selection: dict[str, Any] = {"reference": REFERENCE, "candidates": {},
                                 "not_candidates_ru": {"W2_obs_fcst_oracle": "идеальный прогноз — только верхняя оценка",
                                                       "P1_obs_placebo": "плацебо", "P3_no_calendar_placebo": "плацебо"}}
    passed = []
    for c, placebo in CANDIDATES.items():
        cp = pooled[c]
        vs_ref = comps[f"{c}_vs_M0"]
        vs_placebo = comps[f"{c}_vs_placebo"]
        g = {
            "g1_primary_ci95_above_zero": bool(low(vs_ref, "episode_recall_50_72h") > 0),
            "g2_episode_precision_not_worse_by_0.01": bool((cp["episode_precision"] or 0) >= (ref["episode_precision"] or 0) - 0.01),
            "g3_false_alerts_within_limit": bool((cp["false_alerts_per_1000"] or 0) <= (ref["false_alerts_per_1000"] or 0) + max(1.0, 0.05 * (ref["false_alerts_per_1000"] or 0))),
            "g5_beats_strongest_baseline_pr_auc": bool(low(comps[f"{c}_vs_strongest_baseline"], "pr_auc") > 0),
            "g6_beats_own_placebo_pr_auc": bool(low(vs_placebo, "pr_auc") > 0),
        }
        if unseen_events < min_pos or unseen(c, "pr_auc") is None or unseen(REFERENCE, "pr_auc") is None:
            g["g4_unseen_not_worse_by_0.01"] = "insufficient_support"
        else:
            g["g4_unseen_not_worse_by_0.01"] = bool(unseen(c, "pr_auc") >= unseen(REFERENCE, "pr_auc") - 0.01
                                                   and unseen(c, "episode_recall_50_72h") >= unseen(REFERENCE, "episode_recall_50_72h") - 0.01)
        ok = all(v is True or v == "insufficient_support" for v in g.values())
        selection["candidates"][c] = {"placebo": placebo, "gates": g, "passed": ok, "failed": [k for k, v in g.items() if v is False]}
        if ok:
            passed.append(c)
    if passed:
        best = max(passed, key=lambda c: (pooled[c]["episode_recall"], pooled[c]["episode_precision"]))
        selection.update(selected=best, reason="passed_all_gates_vs_M0")
    else:
        selection.update(selected=REFERENCE, reason="no_weather_candidate_passed_gates_keep_M0_without_improvement_claim")
    result["selection"] = selection

    def decide(entry: dict[str, Any], metric: str) -> dict[str, str]:
        c = entry.get("mean_over_folds", {}).get(metric)
        if not c or c["ci95_low"] is None:
            return {"decision": "inconclusive", "reason": "NO_FINITE_BOOTSTRAP"}
        if c["ci95_low"] > 0:
            return {"decision": "confirmed", "reason": "CI95_ABOVE_ZERO"}
        if c["ci95_high"] < 0:
            return {"decision": "rejected", "reason": "CI95_BELOW_ZERO"}
        return {"decision": "inconclusive", "reason": "CI95_INCLUDES_ZERO"}

    def not_worse(entry: dict[str, Any], tol: float = 0.01) -> dict[str, str]:
        c = entry.get("mean_over_folds", {}).get("pr_auc")
        if not c or c["ci95_low"] is None:
            return {"decision": "inconclusive", "reason": "NO_FINITE_BOOTSTRAP"}
        if c["ci95_low"] > -tol:
            return {"decision": "confirmed", "reason": "LOSS_BOUNDED_BY_0.01_AT_CI95"}
        if c["ci95_high"] < 0:
            return {"decision": "rejected", "reason": "SIGNIFICANT_LOSS"}
        return {"decision": "inconclusive", "reason": "CI95_ALLOWS_LOSS_ABOVE_0.01"}

    repro = [folds[f]["m0_reproduction"]["matches_within_0.002"] for f in folds]
    result["hypotheses"] = {
        "W0_m0_reproduces_notebook_05": {"decision": "confirmed" if all(repro) else ("not_applicable_smoke" if result["mode"] == "SMOKE" else "rejected"),
                                         "reason": "PR_AUC_WITHIN_0.002_EACH_FOLD" if all(repro) else "SEE_m0_reproduction"},
        "W1_obs_weather_improves_primary": decide(comps["W1_obs_vs_M0"], "episode_recall_50_72h"),
        "W1_obs_weather_improves_pr_auc": decide(comps["W1_obs_vs_M0"], "pr_auc"),
        "W1_real_weather_beats_placebo_pr_auc": decide(comps["W1_obs_vs_placebo"], "pr_auc"),
        "W2_oracle_forecast_adds_over_obs_pr_auc": decide(comps["W2_fcst_oracle_vs_W1"], "pr_auc"),
        "W2_oracle_forecast_adds_over_obs_primary": decide(comps["W2_fcst_oracle_vs_W1"], "episode_recall_50_72h"),
        "W3_weather_replaces_calendar_not_worse_than_M0": not_worse(comps["W3_no_calendar_obs_vs_M0"]),
        "W3_weather_adds_to_no_calendar_pr_auc": decide(comps["W3_no_calendar_obs_vs_NC"], "pr_auc"),
    }


def finish_weather(result: dict[str, Any], out_dir: Path, started: float, keys: set[str]) -> dict[str, Any]:
    result["runtime_seconds"] = round(time.perf_counter() - started, 1)
    result = _clean(result)
    text = json.dumps(result, ensure_ascii=False, indent=2, default=_json_default)
    leaked = {k for k in keys if len(k) >= 8} & set(re.findall(r"[A-Za-z0-9_\-]+", text))
    if leaked:
        raise RuntimeError(f"В результатах обнаружены идентификаторы ({len(leaked)}) — запись остановлена")
    (out_dir / "results_weather_pre2025.json").write_text(text, encoding="utf-8")
    (out_dir / "summary_weather_ru.md").write_text(render_weather(result), encoding="utf-8")
    log("Записано: results_weather_pre2025.json, summary_weather_ru.md")
    return result


# ---------------------------------------------------------------------------
# 3. Сводка
# ---------------------------------------------------------------------------
def _fmt(v: Any, d: int = 4) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "да" if v else "нет"
    if isinstance(v, int):
        return f"{v:,}".replace(",", " ")
    return f"{float(v):.{d}f}"


def _ci_s(c: dict[str, Any] | None) -> str:
    if not isinstance(c, dict) or c.get("ci95_low") is None:
        return "—"
    return f"{c['mean_difference']:+.4f} [{c['ci95_low']:+.4f}; {c['ci95_high']:+.4f}]"


TITLES_RU = {
    "B2_recurrence": "B2 recurrence-скор", "B3_rule": "B3 правило", "B4_logistic": "B4 логистическая регрессия",
    "M0_lightgbm": "M0 LightGBM (как в 05)", "W1_obs": "W1: M0 + погода до конца D",
    "P1_obs_placebo": "P1: M0 + плацебо-погода (+364 сут)", "W2_obs_fcst_oracle": "W2: W1 + идеальный прогноз D+1…D+2",
    "NC_no_calendar": "NC: M0 без календаря", "W3_no_calendar_obs": "W3: без календаря + погода до конца D",
    "P3_no_calendar_placebo": "P3: без календаря + плацебо-погода",
}
WEATHER_DECISION_RU = {"confirmed": "подтверждено", "rejected": "отклонено", "inconclusive": "не определено",
               "not_applicable_smoke": "не применимо (SMOKE)"}


def render_weather(r: dict[str, Any]) -> str:
    L = ["# 05W · Погода как признак прогноза отказов", "",
         f"Статус: **{r.get('status')}** · режим **{r.get('mode')}** · `{r.get('comparability')}`", "",
         "Цель — `target_failure_state_onset_24h` (proxy: `Неисправен`/`Обесточен` в D+2), фолды, семплирование и модель — "
         "как в основном прогоне 05. План зафиксирован до обучения: `docs/EXPERIMENT_05W_WEATHER_RU.md`.", "",
         "Погода: Open-Meteo (реанализ ERA5), одна точка на Москву, сутки по Europe/Moscow; лицензия CC BY 4.0 "
         "(«Weather data by Open-Meteo.com»). Погодные признаки одинаковы для всех каналов в сутки.", ""]
    if r.get("mode") == "SMOKE":
        L += ["> **SMOKE**: подвыборка каналов и деревьев; числа несравнимы.", ""]
    if r.get("status") not in ("completed", "completed_smoke_non_comparable"):
        L += ["## Остановка", "", f"Причина: {r.get('stop_reason')}", ""]
        return "\n".join(L) + "\n"
    L += ["## Воспроизведение M0", ""]
    for f, v in r["folds"].items():
        m = v["m0_reproduction"]
        same = "не проверяется (SMOKE)" if r.get("mode") == "SMOKE" else _fmt(m["matches_within_0.002"])
        L.append(f"- {f}: PR-AUC {_fmt(m['pr_auc_this_run'])} (в FULL-прогоне 05: {_fmt(m['pr_auc_notebook_05_full'])}), совпадает: {same}.")
    cfg = r["config"]
    L += ["", f"## Модели (среднее по фолдам; эпизоды {cfg['alert_budget_per_day']} каналов/сутки, cooldown {cfg['cooldown_hours']} ч)", "",
          "| модель | PR-AUC | episode recall | episode precision | ложных / 1000 | Brier | ECE |",
          "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for n, p in r["pooled_mean_over_folds"].items():
        L.append(f"| {TITLES_RU.get(n, n)} | {_fmt(p['pr_auc'])} | {_fmt(p['episode_recall'])} | {_fmt(p['episode_precision'])} | "
                 f"{_fmt(p['false_alerts_per_1000'], 1)} | {_fmt(p['brier'])} | {_fmt(p['ece'])} |")
    L += ["", "По фолдам, PR-AUC:", "", "| модель | " + " | ".join(r["folds"]) + " |", "| --- |" + " ---: |" * len(r["folds"])]
    for n in r["pooled_mean_over_folds"]:
        L.append(f"| {TITLES_RU.get(n, n)} | " + " | ".join(_fmt(v["models"][n]["point"]["pr_auc"]) for v in r["folds"].values()) + " |")
    L += ["", "## Парные 95% CI (кандидат − референс, среднее по фолдам)", "",
          "| сравнение | Δ PR-AUC | Δ episode recall | Δ episode precision |", "| --- | ---: | ---: | ---: |"]
    for c in r["paired_bootstrap"]["comparisons"].values():
        m = c.get("mean_over_folds", {})
        L.append(f"| {c['difference']} | {_ci_s(m.get('pr_auc'))} | {_ci_s(m.get('episode_recall_50_72h'))} | {_ci_s(m.get('episode_precision_50_72h'))} |")
    L += ["", "## По типам датчиков (описательно)", "",
          "Δ PR-AUC, среднее по фолдам с ≥ 20 positives данного типа.", "",
          "| тип | W1 − M0 | W1 − плацебо | W2 − M0 | фолдов |", "| --- | ---: | ---: | ---: | ---: |"]
    for t_name, entry in r["paired_bootstrap"]["by_sensor_type_descriptive"].items():
        get = lambda k: entry[k].get("mean_over_folds", {}).get("pr_auc")  # noqa: E731
        L.append(f"| {t_name} | {_ci_s(get('W1_obs_vs_M0'))} | {_ci_s(get('W1_obs_vs_placebo'))} | "
                 f"{_ci_s(get('W2_fcst_oracle_vs_M0'))} | {entry['W1_obs_vs_M0'].get('folds_used', 0)} |")
    L += ["", "## Доля gain погодных и календарных признаков", "",
          "| модель | " + " | ".join(f"{f}: погода / календарь" for f in r["folds"]) + " |", "| --- |" + " ---: |" * len(r["folds"])]
    for n in ("M0_lightgbm", "W1_obs", "P1_obs_placebo", "W2_obs_fcst_oracle", "W3_no_calendar_obs"):
        cells = []
        for v in r["folds"].values():
            imp = v["feature_importance_gain_share"]["models"][n]
            cells.append(f"{imp['weather_gain_share']:.3f} / {imp['calendar_gain_share']:.3f}")
        L.append(f"| {TITLES_RU.get(n, n)} | " + " | ".join(cells) + " |")
    L += ["", "Доля gain — predictive association, не причинность.", "",
          "## Гипотезы", "", "| гипотеза | решение | причина |", "| --- | --- | --- |"]
    for k, h in r["hypotheses"].items():
        L.append(f"| `{k}` | **{WEATHER_DECISION_RU.get(h['decision'], h['decision'])}** | `{h['reason']}` |")
    s = r["selection"]
    L += ["", "## Отбор", "", "| кандидат | прошёл | не пройдены |", "| --- | --- | --- |"]
    for c, v in s["candidates"].items():
        L.append(f"| {TITLES_RU.get(c, c)} | {_fmt(v['passed'])} | {', '.join(v['failed']) or '—'} |")
    L += ["", f"**Выбрано: `{s['selected']}`** (`{s['reason']}`). Сильнейший baseline: `{r['paired_bootstrap']['strongest_baseline']}`.", "",
          "## Ограничения", "",
          "- Одна точка погоды на весь город: признак даты, а не объекта; локальные ливни и подтопления не видны.",
          "- W2 использует фактическую погоду D+1…D+2 как «идеальный прогноз» — это верхняя оценка; реальный прогноз хуже.",
          "- Плацебо сохраняет день недели и сезон, но не межгодовые тренды парка; сравнение с ним — проверка на сезонный shortcut.",
          "- Proxy-цель по журналу, не подтверждённые поломки. Два pre-2025 фолда, не финальный тест; 2025+ не загружался.", "",
          f"Время прогона: {r.get('runtime_seconds')} с."]
    return "\n".join(L) + "\n"


def make_config_weather(mode: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    config = make_config(mode)
    config.update({"alert_budget_per_day": 50, "cooldown_hours": 72})
    config.update(overrides or {})
    return config


# ---------------------------------------------------------------------------
# 4. Самопроверки
# ---------------------------------------------------------------------------
def run_weather_self_tests() -> dict[str, bool]:
    import polars as pl

    weather = load_weather()
    report = {"weather_sha256_and_continuity": weather.height == 2557}
    feats = weather_features(weather)
    # W_OBS на дату D не зависит от погоды после D; W_FCST на D не зависит от D+3 и позже
    cut = date(2023, 6, 15)
    changed = weather.with_columns([pl.when(pl.col("date") > cut + timedelta(days=2)).then(99.0).otherwise(pl.col(c)).alias(c)
                                    for c in RAW_WEATHER_COLUMNS])
    f2 = weather_features(changed)
    at = lambda f, d: f.filter(pl.col("d_cutoff_date") == d)  # noqa: E731
    a, b = at(feats, cut), at(f2, cut)
    assert a.select(W_OBS + W_FCST).equals(b.select(W_OBS + W_FCST)), "утечка будущего в признаки"
    changed_d2 = weather.with_columns([pl.when(pl.col("date") == cut + timedelta(days=2)).then(99.0).otherwise(pl.col(c)).alias(c)
                                       for c in RAW_WEATHER_COLUMNS])
    c = at(weather_features(changed_d2), cut)
    assert a.select(W_OBS).equals(c.select(W_OBS)) and not a.select(W_FCST).equals(c.select(W_FCST))
    report["obs_features_causal"] = True
    report["forecast_uses_exactly_dplus1_dplus2"] = True
    # значения: осадки за 3 суток, прогноз, плацебо
    w = {r["date"]: r for r in weather.iter_rows(named=True)}
    row = at(feats, cut).row(0, named=True)
    exp3 = sum(w[cut - timedelta(days=k)]["precipitation_sum"] for k in range(3))
    assert abs(row["w_precip_3d"] - exp3) < 1e-4
    exp_fc = w[cut + timedelta(days=1)]["precipitation_sum"] + w[cut + timedelta(days=2)]["precipitation_sum"]
    assert abs(row["w_fc_precip_2d"] - exp_fc) < 1e-4
    assert abs(row["wp_t_mean_d0"] - w[cut + timedelta(days=PLACEBO_SHIFT_DAYS)]["temperature_2m_mean"]) < 1e-4
    assert (cut + timedelta(days=PLACEBO_SHIFT_DAYS)).weekday() == cut.weekday()
    report["feature_values_match_manual"] = True
    report["placebo_same_weekday_other_year"] = True
    for f in MODELS.values():
        assert_safe_features(f + list(CATEGORICAL_FEATURES))
    report["feature_sets_safe"] = True
    return report
