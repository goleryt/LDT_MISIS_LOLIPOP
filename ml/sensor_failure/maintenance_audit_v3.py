"""Ноутбук 17: read-only audit переданного газового bundle внутри/вне окон сервисных работ (без обучения).

Спецификация согласована заранее (Drive 38–44, docs/AUDIT_17_MAINTENANCE_RU.md):
- скорится НЕИЗМЕНЁННЫЙ gas_cross_v3_bundle (predictor.py + model.txt) и правило R1 на одних и тех же строках;
- периоды: 2025 H2 и 2026 H1 — оба уже исследовались проектом, это ретроспективный audit, не нетронутый тест;
- окна работ двух видов, строго раздельно:
  (a) post-hoc: у объекта ВСЕ газовые каналы без показаний ≥ min_silence суток подряд → окно
      [начало молчания − before; конец молчания + after]; использует будущее, только для исследования меток;
  (b) причинный trailing-флаг на D: такое молчание закончилось в [D − lookback; D − 1] и возврат уже наблюдался к D;
- строка попадает в окно, если её день исхода D+2 лежит в окне; цензура симметричная (y = 1, 0 или unknown);
- чувствительность after = 14 / 21 / 30; negative control — те же окна, сдвинутые на +30 и +60 суток;
- метрики на каждой страте: counts, unknown, prevalence, PR-AUC и lift (PR-AUC / prevalence) для G2 и R1, Brier/ECE G2,
  блочный бутстрэп по неделям ΔPR-AUC (G2 − R1); top-25/сутки — ОДНА общая политика с cooldown, разбитая по стратам;
- никаких порогов, выбора модели или изменения bundle; в выходах только агрегаты.

v2 (после проверки GPT, Drive 46):
- preflight: ZIP обязан совпасть с .sha256, а manifest панели, число строк, схема и SHA частей — с тем, что записано
  в bundle.json; иначе PanelMismatch (скорить старой моделью другую панель нельзя);
- молчание считается только между двумя реальными газовыми показаниями объекта внутри наблюдаемого архива
  (нет искусственных интервалов до первого появления объекта и после конца архива);
- окна присваиваются строкам через стабильный индекс строки;
- top-25 и cooldown для G2 и R1 — на одной и той же скорируемой eligible-когорте;
- контрольные сдвинутые окна не пересекаются с основным post-hoc окном.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

import target_models_v3_runtime as rt

TARGET = "target_t4_gas_cross"
GAS_TYPE = "Газовый датчик"
PERIODS = {
    "2025H2": (date(2025, 7, 1), date(2026, 1, 1)),
    "2026H1": (date(2026, 1, 1), date(2026, 7, 1)),
}
CONTROL_SHIFTS = (30, 60)
AFTER_VARIANTS = (14, 21, 30)


def make_config_17(mode: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = rt.make_config_targets(mode)
    cfg.update({"periods": list(PERIODS), "min_silence_days": 4, "before_days": 3, "after_days": 21,
                "lookback_days": 21, "budget_per_day": 25, "bootstrap_reps": 200 if mode == "FULL" else 30,
                "min_positives_for_bootstrap": 30, "clean_history_col": "f_gas_cross_n_30d", "verify_sha256": True})
    cfg.update(overrides or {})
    return cfg


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------
def _sha256(path: Path) -> str:
    return rt.file_sha256(Path(path))


class PanelMismatch(ValueError):
    """Подключённая панель — не та, на которой обучен bundle."""


def check_panel_matches_bundle(manifest: dict[str, Any], manifest_path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    """Строгая сверка панели с bundle.json: SHA manifest, схема, число строк, SHA всех частей."""
    exp = spec.get("panel") or {}
    got = {"manifest_sha256": _sha256(manifest_path), "schema_version": manifest.get("schema_version"),
           "rows": manifest.get("rows"), "parts_sha256": [p["sha256"] for p in manifest.get("parts", [])]}
    bad = [k for k in got if exp.get(k) != got[k]]
    if bad:
        raise PanelMismatch(
            "панель не совпадает с bundle по полям " + ", ".join(bad)
            + f". Найдена панель: manifest_sha256={got['manifest_sha256']}, строк {got['rows']}, "
            + f"путь входа {manifest_path.parent}. Ожидалась: manifest_sha256={exp.get('manifest_sha256')}, "
            + f"строк {exp.get('rows')}. Подключите ту версию выхода 14, на которой обучался 16; проверку не обходить.")
    return {"panel_matches_bundle": True, "manifest_sha256": got["manifest_sha256"], "rows": got["rows"],
            "parts": len(got["parts_sha256"]), "data_end": manifest.get("data_end")}


def find_bundle(input_dir: Path, work_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Ищет gas_cross_v3_bundle.zip во входах; ZIP обязан совпасть с gas_cross_v3_bundle.zip.sha256 рядом."""
    input_dir = Path(input_dir)
    info: dict[str, Any] = {}
    zips = sorted(input_dir.rglob("gas_cross_v3_bundle.zip"))
    if zips:
        z = zips[0]
        info["zip_sha256"] = _sha256(z)
        side = list(z.parent.glob("gas_cross_v3_bundle.zip.sha256"))
        if not side:
            raise FileNotFoundError("рядом с gas_cross_v3_bundle.zip нет gas_cross_v3_bundle.zip.sha256")
        expected = side[0].read_text(encoding="utf-8").split()[0]
        if expected != info["zip_sha256"]:
            raise ValueError("SHA-256 ZIP не совпадает с .sha256 — это не переданный bundle")
        info["zip_sha256_verified"] = True
        out = Path(work_dir) / "_bundle17"
        if out.exists():
            shutil.rmtree(out)
        with zipfile.ZipFile(z) as f:
            f.extractall(out)
        found = sorted(out.rglob("bundle.json"))
    else:
        raise FileNotFoundError("gas_cross_v3_bundle.zip не найден: подключите dataset с ZIP и .zip.sha256")
    if not found:
        raise FileNotFoundError("в gas_cross_v3_bundle.zip нет bundle.json")
    return found[0].parent, info


def load_predictor(bundle_dir: Path) -> Any:
    spec = importlib.util.spec_from_file_location("gas_bundle_predictor_17", Path(bundle_dir) / "predictor.py")
    module = importlib.util.module_from_spec(spec)
    flag, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = flag
    return module


# ---------------------------------------------------------------------------
# Данные
# ---------------------------------------------------------------------------
def load_period(pl: Any, parts: list[Path], names: list[str], cfg: dict[str, Any], period: tuple[date, date]) -> Any:
    """Selectable строки T4 периода (метка известна или unknown-причина), как в 15/16."""
    reason = "reason_" + TARGET[len("target_"):]
    extra = [c for c in dict.fromkeys(list(rt.TARGET_SPECS[TARGET]["rule"]) + [cfg["clean_history_col"]]) if c not in names]
    lf = pl.scan_parquet(parts)
    cols = lf.collect_schema().names()
    extra = [c for c in extra if c in cols]
    lf = lf.filter((pl.col("d_cutoff_date") >= period[0]) & (pl.col("d_cutoff_date") < period[1])
                   & (pl.col("d_label_decision_end") <= period[1])
                   & (pl.col(TARGET).is_not_null() | pl.col(reason).is_in(rt.UNKNOWN_REASONS)))
    if cfg["mode"] == "SMOKE":
        lf = lf.filter(pl.col("d_channel_key").hash(seed=7) % cfg["smoke_channel_share"] == 0)
    numeric = [c for c in names + extra if c not in rt.CATEGORICAL]
    keep = ["d_channel_key", "d_object_key", "d_cutoff_date", TARGET, reason] + names + extra
    return lf.select(keep).with_columns([pl.col(c).cast(pl.Float32) for c in numeric]).collect()


def object_gas_activity(pl: Any, parts: list[Path], start: date, end: date) -> Any:
    """(объект, сутки) → было ли хоть одно газовое показание (gas_max у газового канала). Полный календарь объекта:
    сутки без строк панели считаются молчанием."""
    lf = (pl.scan_parquet(parts)
          .filter((pl.col("тип_датчика") == GAS_TYPE) & pl.col("d_object_key").is_not_null()
                  & (pl.col("d_cutoff_date") >= start) & (pl.col("d_cutoff_date") < end))
          .select("d_object_key", pl.col("d_cutoff_date").alias("day"),
                  pl.col("gas_max").cast(pl.Float64).fill_nan(None).is_not_null().alias("reading")))
    obs = lf.group_by("d_object_key", "day").agg(pl.col("reading").any()).collect()
    days = pl.DataFrame({"day": pl.date_range(start, end - timedelta(days=1), eager=True)})
    objs = obs.select("d_object_key").unique()
    return (objs.join(days, how="cross").join(obs, on=["d_object_key", "day"], how="left")
            .with_columns(pl.col("reading").fill_null(False)).sort("d_object_key", "day"))


def silence_runs(pl: Any, activity: Any, min_silence: int) -> Any:
    """Отрезки молчания всех газовых каналов объекта длиной ≥ min_silence суток: (объект, start, end, returned).

    Учитываются только отрезки, ограниченные реальными показаниями С ОБЕИХ сторон: сутки до первого и после
    последнего показания объекта в наблюдаемом окне не считаются молчанием (объект ещё не появился / архив кончился).
    Поэтому returned всегда True; колонка оставлена для совместимости."""
    bounds = (activity.filter(pl.col("reading")).group_by("d_object_key")
              .agg(pl.col("day").min().alias("_first"), pl.col("day").max().alias("_lastread")))
    activity = (activity.join(bounds, on="d_object_key", how="inner")
                .filter((pl.col("day") >= pl.col("_first")) & (pl.col("day") <= pl.col("_lastread")))
                .drop("_first", "_lastread").sort("d_object_key", "day"))
    # два шага: вложенное .over внутри .over не поддерживается в polars 1.31 (Kaggle)
    a = (activity.with_columns((pl.col("reading") != pl.col("reading").shift(1).over("d_object_key"))
                               .fill_null(True).cast(pl.UInt32).alias("_chg"))
         .with_columns(pl.col("_chg").cum_sum().over("d_object_key").alias("_run")))
    runs = (a.filter(~pl.col("reading")).group_by("d_object_key", "_run")
            .agg(pl.col("day").min().alias("start"), pl.col("day").max().alias("end"), pl.len().alias("length")))
    last_day = activity.group_by("d_object_key").agg(pl.col("day").max().alias("_last"))
    return (runs.filter(pl.col("length") >= min_silence).join(last_day, on="d_object_key")
            .with_columns((pl.col("end") < pl.col("_last")).alias("returned")).drop("_run", "_last"))


def posthoc_days(pl: Any, runs: Any, before: int, after: int, shift: int = 0) -> Any:
    """Дни post-hoc окон (объект, день); shift > 0 — negative control того же размера."""
    w = runs.select("d_object_key",
                    (pl.col("start") - pl.duration(days=before - shift)).alias("a"),
                    (pl.col("end") + pl.duration(days=after + shift)).alias("b"))
    return (w.with_columns(pl.date_ranges("a", "b").alias("day")).explode("day")
            .select("d_object_key", "day").unique())


def trailing_days(pl: Any, runs: Any, lookback: int) -> Any:
    """Причинный флаг: дни D, для которых молчание закончилось в [D − lookback; D − 1] и возврат наблюдался к D."""
    w = runs.filter(pl.col("returned")).select(
        "d_object_key", (pl.col("end") + pl.duration(days=1)).alias("a"), (pl.col("end") + pl.duration(days=lookback)).alias("b"))
    return (w.with_columns(pl.date_ranges("a", "b").alias("day")).explode("day")
            .select("d_object_key", "day").unique())


def mark(pl: Any, frame: Any, days: Any, name: str, offset_days: int) -> Any:
    """Флаг строки: (объект, D + offset_days) входит в набор дней. Выравнивание — по стабильному индексу строки,
    а не по порядку строк после join."""
    key = frame.select(pl.int_range(0, pl.len(), dtype=pl.UInt32).alias("_row"), "d_object_key",
                       (pl.col("d_cutoff_date") + pl.duration(days=offset_days)).alias("day"))
    hits = (key.join(days.select("d_object_key", "day").unique(), on=["d_object_key", "day"], how="semi")
            .get_column("_row").to_numpy())
    flag = np.zeros(frame.height, dtype=bool)
    flag[hits] = True
    return frame.with_columns(pl.Series(name, flag))


# ---------------------------------------------------------------------------
# Метрики
# ---------------------------------------------------------------------------
def select_alerts(days: np.ndarray, chans: np.ndarray, score: np.ndarray, k: int, cooldown: int) -> np.ndarray:
    """Общая политика: top-k строк в сутки с cooldown по каналу; возвращает маску выданных тревог."""
    order = np.lexsort((-score, days))
    picked = np.zeros(len(days), dtype=bool)
    last: dict[Any, int] = {}
    cur, taken = None, 0
    for i in order:
        d = int(days[i])
        if d != cur:
            cur, taken = d, 0
        if taken >= k:
            continue
        ch = chans[i]
        if ch in last and d - last[ch] < cooldown:
            continue
        last[ch] = d
        picked[i] = True
        taken += 1
    return picked


def _block_bootstrap(y: np.ndarray, a: np.ndarray, b: np.ndarray, weeks: np.ndarray, reps: int, seed: int) -> dict[str, Any]:
    r = rt.paired_bootstrap(y, a, b, weeks, reps, seed)
    return {"delta_mean": r["mean"], "ci95_low": r["ci95_low"], "ci95_high": r["ci95_high"], "reps": r["reps"]}


def stratum_metrics(mask: np.ndarray, y_all: np.ndarray, g2: np.ndarray, g2_cal: np.ndarray, r1: np.ndarray,
                    weeks: np.ndarray, alerts: np.ndarray, cfg: dict[str, Any]) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score

    known = mask & (y_all >= 0)
    y = y_all[known]
    pos = int((y == 1).sum())
    out: dict[str, Any] = {"selectable": int(mask.sum()), "known": int(known.sum()), "positives": pos,
                           "unknown_share": float(1 - known.sum() / max(mask.sum(), 1)),
                           "prevalence": float(y.mean()) if len(y) else None}
    ok = len(y) > 0 and 0 < pos < len(y)
    if ok:
        pg, pr = float(average_precision_score(y, g2[known])), float(average_precision_score(y, r1[known]))
        out.update({"pr_auc_G2": pg, "pr_auc_R1": pr, "lift_G2": pg / out["prevalence"], "lift_R1": pr / out["prevalence"],
                    "brier_G2": float(np.mean((g2_cal[known] - y) ** 2)), "ece10_G2": rt.ece(y, g2_cal[known])})
        if pos >= cfg["min_positives_for_bootstrap"]:
            out["bootstrap_G2_minus_R1"] = _block_bootstrap(y, g2[known], r1[known], weeks[known],
                                                             cfg["bootstrap_reps"], cfg["random_seed"])
    a = mask & alerts
    out["top_k_alerts"] = {"alerts": int(a.sum()), "known": int((a & (y_all >= 0)).sum()),
                           "true_positive": int((a & (y_all == 1)).sum()), "unknown": int((a & (y_all < 0)).sum())}
    return out


# ---------------------------------------------------------------------------
# Прогон
# ---------------------------------------------------------------------------
def run_audit_17(cfg: dict[str, Any], log: Any = print) -> dict[str, Any]:
    import polars as pl

    t0 = time.time()
    out_dir = Path(cfg["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    parts, manifest = rt.discover_panel(Path(cfg["input_dir"]), cfg["verify_sha256"])
    manifest_path = sorted(Path(cfg["input_dir"]).rglob("panel_manifest_v3.json"))[0]
    bdir, binfo = find_bundle(Path(cfg["input_dir"]), out_dir)
    pred = load_predictor(bdir)
    bundle = pred.load_bundle(bdir)
    spec = bundle["spec"]
    panel_info = check_panel_matches_bundle(manifest, manifest_path, spec)
    names = [f["name"] for f in spec["features"]]
    log(f"панель {manifest['rows']:,} строк; bundle {spec.get('model_version', spec['model_sha256'][:12])}, признаков {len(names)}")
    first = min(p[0] for p in PERIODS.values()) - timedelta(days=90)
    last = max(p[1] for p in PERIODS.values()) + timedelta(days=90)
    if manifest.get("data_end"):
        last = min(last, date.fromisoformat(str(manifest["data_end"])[:10]) + timedelta(days=1))
    activity = object_gas_activity(pl, parts, first, last)
    runs = silence_runs(pl, activity, cfg["min_silence_days"])
    windows = {f"posthoc_after{a}": posthoc_days(pl, runs, cfg["before_days"], a) for a in AFTER_VARIANTS}
    controls = {f"control_shift{s}": posthoc_days(pl, runs, cfg["before_days"], cfg["after_days"], s) for s in CONTROL_SHIFTS}
    main_window = windows[f"posthoc_after{cfg['after_days']}"]
    controls = {k: v.join(main_window, on=["d_object_key", "day"], how="anti") for k, v in controls.items()}
    trailing = trailing_days(pl, runs, cfg["lookback_days"])
    payload: dict[str, Any] = {
        "status": None, "mode": cfg["mode"], "bundle": {"model_sha256": spec["model_sha256"],
                                                        "model_version": spec.get("model_version"), **binfo},
        "panel": panel_info, "audit_version": "17-v2",
        "protocol": {k: cfg[k] for k in ("min_silence_days", "before_days", "after_days", "lookback_days", "budget_per_day",
                                         "bootstrap_reps", "cooldown_days")},
        "note": ("ретроспективный audit: 2025 H2 и 2026 H1 уже исследовались; post-hoc окна используют будущее и "
                 "не являются backend-правилом; ничего не выбирается"),
        "silence_runs": {"objects": int(activity["d_object_key"].n_unique()), "runs": runs.height,
                         "median_length_days": float(runs["length"].median()) if runs.height else None},
        "periods": {}}
    for pname in cfg["periods"]:
        period = PERIODS[pname]
        frame = load_period(pl, parts, names, cfg, period)
        if frame.height == 0:
            payload["periods"][pname] = {"status": "no_rows"}
            continue
        for wname, days in {**windows, **controls}.items():
            frame = mark(pl, frame, days, wname, 2)          # окно исхода = D + 2
        frame = mark(pl, frame, trailing, "trailing_flag_at_D", 0)
        records = frame.select([pl.col("d_cutoff_date").cast(pl.String).alias("as_of_date")] + names).to_pandas()
        res = pred.predict(records, bundle)
        g2 = np.array([np.nan if r["raw_score"] is None else r["raw_score"] for r in res], dtype=float)
        g2_cal = np.array([np.nan if r["score"] is None else r["score"] for r in res], dtype=float)
        eligible = ~np.isnan(g2)
        r1 = rt.rule_score(frame, rt.TARGET_SPECS[TARGET])
        y_all = frame[TARGET].fill_null(-1).to_numpy().astype(int)
        days = np.array([(d - date(2019, 1, 1)).days for d in frame["d_cutoff_date"].to_list()])
        weeks = days // 7
        chans = frame["d_channel_key"].to_numpy()
        g2f = np.nan_to_num(g2, nan=-1.0)
        # одна и та же скорируемая когорта для обеих политик: abstain не занимает слот тревоги
        idx = np.flatnonzero(eligible)
        alerts = np.zeros(frame.height, dtype=bool)
        alerts_r1 = np.zeros(frame.height, dtype=bool)
        alerts[idx] = select_alerts(days[idx], chans[idx], g2f[idx], cfg["budget_per_day"], cfg["cooldown_days"])
        alerts_r1[idx] = select_alerts(days[idx], chans[idx], np.asarray(r1)[idx], cfg["budget_per_day"], cfg["cooldown_days"])
        clean = (frame[cfg["clean_history_col"]].fill_null(0).to_numpy() == 0) if cfg["clean_history_col"] in frame.columns \
            else np.ones(frame.height, dtype=bool)
        base = eligible
        strata: dict[str, np.ndarray] = {"all": base}
        for wname in list(windows) + list(controls):
            m = frame[wname].to_numpy()
            strata[f"{wname}:in"], strata[f"{wname}:out"] = base & m, base & ~m
        tf = frame["trailing_flag_at_D"].to_numpy()
        strata["trailing_flag_at_D:true"], strata["trailing_flag_at_D:false"] = base & tf, base & ~tf
        main_out = ~frame[f"posthoc_after{cfg['after_days']}"].to_numpy()
        strata["clean30d"] = base & clean
        strata["clean30d_and_posthoc_out"] = base & clean & main_out
        pr: dict[str, Any] = {"rows_selectable": frame.height, "rows_scored": int(eligible.sum()),
                              "alerts_policy": f"top-{cfg['budget_per_day']}/сутки, cooldown {cfg['cooldown_days']} сут, "
                                               "G2 и R1 на одной eligible-когорте",
                              "strata": {}}
        for sname, m in strata.items():
            st = stratum_metrics(m, y_all, g2f, np.nan_to_num(g2_cal), r1, weeks, alerts, cfg)
            st["top_k_alerts_R1_policy"] = {"alerts": int((m & alerts_r1).sum()), "true_positive": int((m & alerts_r1 & (y_all == 1)).sum()),
                                            "unknown": int((m & alerts_r1 & (y_all < 0)).sum())}
            pr["strata"][sname] = st
        # специфичность: обогащение положительных внутри окна по сравнению со сдвинутыми окнами
        enrich = {}
        for wname in [f"posthoc_after{cfg['after_days']}"] + list(controls):
            i, o = pr["strata"][f"{wname}:in"], pr["strata"][f"{wname}:out"]
            enrich[wname] = (i["prevalence"] / o["prevalence"]) if i.get("prevalence") and o.get("prevalence") else None
        pr["positive_enrichment_in_vs_out"] = enrich
        payload["periods"][pname] = pr
        log(f"{pname}: selectable {frame.height:,}, скорено {int(eligible.sum()):,}; "
            f"обогащение в окне {enrich.get('posthoc_after' + str(cfg['after_days']))}")
    payload["status"] = "completed_smoke_non_comparable" if cfg["mode"] == "SMOKE" else "completed"
    payload["runtime_s"] = round(time.time() - t0, 1)
    (out_dir / "results_17_maintenance_audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_jd),
                                                                encoding="utf-8")
    (out_dir / "summary_17_maintenance_audit_ru.md").write_text(summary_markdown(payload, cfg), encoding="utf-8")
    return payload


def _jd(o: Any) -> Any:
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, date):
        return o.isoformat()
    raise TypeError(type(o).__name__)


def _f(x: Any, d: int = 3) -> str:
    return "—" if x is None else f"{x:.{d}f}"


def summary_markdown(p: dict[str, Any], cfg: dict[str, Any]) -> str:
    main = f"posthoc_after{cfg['after_days']}"
    L = [f"# 17 · Audit газового bundle внутри/вне окон сервисных работ — {p['status']}", "",
         f"Bundle `{p['bundle'].get('model_version') or p['bundle']['model_sha256'][:12]}` не менялся; обучения нет. {p['note']}.", "",
         f"Окно работ: все газовые каналы объекта без показаний ≥ {cfg['min_silence_days']} суток → "
         f"[начало − {cfg['before_days']}; конец + {cfg['after_days']}] (post-hoc). Причинный флаг: молчание закончилось "
         f"в последние {cfg['lookback_days']} суток. Строка в окне, если день исхода D+2 в окне.", "",
         f"Версия audit: {p.get('audit_version')}. Панель совпадает с bundle: {p['panel']['panel_matches_bundle']} "
         f"(manifest {p['panel']['manifest_sha256'][:12]}…, строк {p['panel']['rows']:,}); ZIP сверен с .sha256.", "",
         f"Найдено отрезков молчания (только между двумя реальными показаниями): {p['silence_runs']['runs']} на "
         f"{p['silence_runs']['objects']} объектах (медиана {_f(p['silence_runs']['median_length_days'], 1)} сут). "
         "Контрольные окна не пересекаются с основным; тревоги G2 и R1 — на одной eligible-когорте.", ""]
    for pname, pr in p["periods"].items():
        if "strata" not in pr:
            continue
        L += [f"## {pname}", "",
              "| страта | selectable | известно | 1 | prevalence | PR-AUC G2 | PR-AUC R1 | lift G2 | lift R1 | ΔPR-AUC G2−R1 [95 %] | top-25: тревог / верных / unknown |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        show = ["all", f"{main}:in", f"{main}:out", "posthoc_after14:out", "posthoc_after30:out",
                "control_shift30:in", "control_shift60:in", "trailing_flag_at_D:true", "trailing_flag_at_D:false",
                "clean30d", "clean30d_and_posthoc_out"]
        for s in show:
            st = pr["strata"].get(s)
            if not st:
                continue
            b = st.get("bootstrap_G2_minus_R1")
            ci = f"{_f(b['delta_mean'])} [{_f(b['ci95_low'])}; {_f(b['ci95_high'])}]" if b and b.get("delta_mean") is not None else "—"
            a = st["top_k_alerts"]
            L.append(f"| {s} | {st['selectable']:,} | {st['known']:,} | {st['positives']:,} | {_f(st['prevalence'], 4)} | "
                     f"{_f(st.get('pr_auc_G2'))} | {_f(st.get('pr_auc_R1'))} | {_f(st.get('lift_G2'), 1)} | {_f(st.get('lift_R1'), 1)} | "
                     f"{ci} | {a['alerts']:,} / {a['true_positive']:,} / {a['unknown']:,} |")
        e = pr["positive_enrichment_in_vs_out"]
        L += ["", "Обогащение положительных (prevalence в окне / вне окна): реальные окна "
              f"{_f(e.get(main), 1)}×, сдвинутые на +30 — {_f(e.get('control_shift30'), 1)}×, на +60 — {_f(e.get('control_shift60'), 1)}×.", ""]
    L += ["## Как читать", "",
          "- Сравнивать lift (PR-AUC / prevalence) и ΔPR-AUC с R1 внутри одной страты, а не голые PR-AUC между стратами.",
          "- Если вне окон G2 ≈ R1 — прогноз реальной газовой опасности не подтверждён; если G2 > R1 с интервалом выше 0 — "
          "сигнал вне сервисных периодов есть (природа не доказана).",
          "- Обогащение в реальных окнах, заметно большее, чем в сдвинутых, — свидетельство связи положительных с работами.",
          "- Ключей каналов/объектов и построчных прогнозов в выходах нет.", ""]
    return "\n".join(L)
