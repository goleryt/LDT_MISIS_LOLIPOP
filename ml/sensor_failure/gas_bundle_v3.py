"""Ноутбук 16: единственный финальный train G2_no_calendar для target_t4_gas_cross и исполняемый bundle для backend.

Решения зафиксированы до запуска (Drive 22–27, docs/EXPORT_16_GAS_BUNDLE_V3_RU.md):
- цель и модель не выбираются заново: G2_no_calendar из ноутбука 15 (те же признаки без календаря, гиперпараметры,
  выборка отрицательных 30:1 с весами, seed); код обучения — функции target_models_v3_runtime без изменений;
- один рецепт на прогон (RECIPE): refit_2025h1 (train < 2025, Platt на 2025 H1, audit 2025 H2)
  или fold_2024_exact (точное воспроизведение fold_2024 из 15); audit ничего не выбирает;
- остановка до обучения, если в калибровке < 30 известных положительных (решение по числу строк, не по метрикам);
- выход: bundle без pickle (model.txt LightGBM, bundle.json, predictor.py, код признаков 14, контракт, пример,
  requirements, SHA-256) + audit и acceptance — только агрегаты, без ключей каналов и построчных прогнозов.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

import target_models_v3_runtime as rt

TARGET = "target_t4_gas_cross"
MODEL_NAME = "G2_no_calendar"
BUNDLE_SCHEMA = "gas_cross_bundle_v3.1"
TARGET_CODE = "gas_threshold_cross_1pct_d2_proxy_v3"
RECIPES: dict[str, dict[str, Any]] = {
    "refit_2025h1": {"train_end": date(2025, 1, 1), "calibration": (date(2025, 1, 1), date(2025, 7, 1)),
                     "audit": (date(2025, 7, 1), date(2026, 1, 1))},
    "fold_2024_exact": {"train_end": date(2024, 1, 1), "calibration": (date(2024, 1, 1), date(2024, 7, 1)),
                        "audit": (date(2024, 7, 1), date(2025, 1, 1))},
}
DEFAULT_RECIPE = "refit_2025h1"
HISTORY_DAYS_REQUIRED = 400
EXPECTED_15_G2_FOLD_2024_PR_AUC = 0.39233349861671724
BUNDLE_DIR_NAME = "gas_cross_v3_bundle"


class RecipeStop(RuntimeError):
    """Рецепт нельзя обучить по заранее заданному правилу (мало положительных) — решение за человеком."""


class ReleaseBlocked(RuntimeError):
    """Release gate не пройден (сверка с 15 или приёмка): принятый bundle не выдаётся."""


def make_config_export(mode: str, recipe: str = DEFAULT_RECIPE, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    if recipe not in RECIPES:
        raise ValueError(f"RECIPE должен быть одним из {list(RECIPES)}")
    cfg = rt.make_config_targets(mode)
    cfg.update({"recipe": recipe, "min_calibration_positives": 30, "min_train_positives": 30,
                "acceptance_rows": 20_000, "latency_rows": 100_000, "latency_budget_s": 300.0,
                # PR-AUC G2 fold_2024 из results_15_v3.json (FULL, 2026-09-24): проверка, что код экспорта = код 15
                "expected_15_fold_2024_pr_auc": EXPECTED_15_G2_FOLD_2024_PR_AUC if mode == "FULL" else None,
                "reproduction_tolerance": 1e-3,
                "code_dir": os.environ.get("LDT_CODE_DIR", str(Path(__file__).resolve().parent))})
    cfg.update(overrides or {})
    return cfg


def _json_default(o: Any) -> Any:
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(f"не сериализуется в JSON: {type(o).__name__}")


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=_json_default)


def _sha256_file(path: Path) -> str:
    return rt.file_sha256(Path(path))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def g2_features(manifest: dict[str, Any], columns: list[str]) -> list[str]:
    """Тот же список, что у G2 в 15: allowlist manifest + справочник, минус календарь. Число не задаётся вручную."""
    return [c for c in rt.safe_features(manifest, columns) if c not in rt.CALENDAR]


def recipe_fold(name: str) -> dict[str, Any]:
    r = RECIPES[name]
    return {"name": name, "train_end": r["train_end"], "calibration": r["calibration"], "validation": r["audit"]}


# ---------------------------------------------------------------------------
# Обучение и audit
# ---------------------------------------------------------------------------
def train_final(pl: Any, frame: Any, feats: list[str], cfg: dict[str, Any], log: Any = print) -> dict[str, Any]:
    fold = recipe_fold(cfg["recipe"])
    train, cal, audit_all = rt.split_fold(pl, frame, fold)
    known = pl.col(TARGET).is_not_null()
    train, cal = train.filter(known), cal.filter(known)
    counts = {"train": train.height, "train_pos": int(train[TARGET].sum() or 0),
              "calibration": cal.height, "calibration_pos": int(cal[TARGET].sum() or 0),
              "audit_selectable": audit_all.height, "audit_known": int(audit_all[TARGET].is_not_null().sum())}
    log(f"рецепт {cfg['recipe']}: train {counts['train']:,} (1: {counts['train_pos']:,}), "
        f"калибровка {counts['calibration']:,} (1: {counts['calibration_pos']:,}), audit selectable {counts['audit_selectable']:,}")
    if counts["calibration_pos"] < cfg["min_calibration_positives"] or counts["train_pos"] < cfg["min_train_positives"]:
        raise RecipeStop(f"рецепт {cfg['recipe']}: положительных в train {counts['train_pos']}, в калибровке "
                         f"{counts['calibration_pos']} (нужно ≥ {cfg['min_train_positives']} / "
                         f"≥ {cfg['min_calibration_positives']}). Обучение не запускалось; решение о рецепте — за Дашей.")
    t0 = time.time()
    tr = rt.sample_train(pl, train, TARGET, cfg)
    model = rt.LightGBM().fit(tr, TARGET, feats, cfg)
    raw_cal = model.score(cal)
    y_cal = cal[TARGET].to_numpy().astype(int)
    platt = rt.platt(raw_cal, y_cal, True)
    if platt is None:
        raise RecipeStop("в калибровке один класс — Platt не определён")
    counts["train_sampled"] = tr.height
    log(f"обучение и калибровка: {time.time() - t0:.0f} с")
    return {"model": model, "platt": platt, "counts": counts, "audit_all": audit_all,
            "prior": float(train[TARGET].mean()), "fit_s": round(time.time() - t0, 1),
            "calibration_ece10": rt.ece(y_cal, rt.apply_platt(platt, raw_cal, True, 0.0)),
            "calibration_prevalence": float(y_cal.mean())}


def runtime_eligible(frame: Any, thr: float) -> np.ndarray:
    n7 = frame["f_gas_n_7d"].to_numpy().astype(float)
    last = frame["f_gas_last"].to_numpy().astype(float)
    return (np.nan_to_num(n7) > 0) & ~np.isnan(last) & (last < thr)


def audit_final(pl: Any, fit: dict[str, Any], cfg: dict[str, Any], thr: float) -> dict[str, Any]:
    """Однократная проверка на отложенном окне рецепта. Ничего не выбирает; R1 — comparator."""
    from sklearn.metrics import average_precision_score, roc_auc_score

    frame = fit["audit_all"]
    if frame.height == 0:
        return {"status": "no_audit_rows"}
    y_all = frame[TARGET].fill_null(-1).to_numpy().astype(int)
    known = y_all >= 0
    days = np.array([(d - date(2019, 1, 1)).days for d in frame["d_cutoff_date"].to_list()])
    chans = frame["d_channel_key"].to_numpy()
    raw_g2 = fit["model"].score(frame)
    raw_r1 = rt.rule_score(frame, rt.TARGET_SPECS[TARGET])
    elig = runtime_eligible(frame, thr)
    out: dict[str, Any] = {"rows_selectable": int(frame.height), "rows_known": int(known.sum()),
                           "positives_known": int((y_all == 1).sum()),
                           "unknown_share_selectable": float(1 - known.mean()),
                           # все selectable строки должны проходить runtime eligibility (она не смотрит в будущее)
                           "runtime_eligible_share_of_selectable": float(elig.mean()), "models": {}}
    y = y_all[known]
    ok = np.unique(y).size == 2
    for name, raw in ((MODEL_NAME, raw_g2), ("R1_rule", raw_r1)):
        budget = rt.budget_curve(days, chans, y_all, raw, cfg["budgets_per_day"], cfg["cooldown_days"])
        for b in budget.values():
            b["alert_unknown_share"] = b["unknown_alerts"] / max(b["alerts"], 1)
            b["alert_unknown_share_cooldown"] = b["unknown_alerts_cooldown"] / max(b["alerts_cooldown"], 1)
        m = {"pr_auc": float(average_precision_score(y, raw[known])) if ok else None,
             "roc_auc": float(roc_auc_score(y, raw[known])) if ok else None, "budget": budget}
        if name == MODEL_NAME:
            p = rt.apply_platt(fit["platt"], raw[known], True, fit["prior"])
            m["brier"] = float(np.mean((p - y) ** 2))
            m["ece10"] = rt.ece(y, p)
        out["models"][name] = m
    out["prevalence_known"] = float(y.mean()) if len(y) else None
    return out


# ---------------------------------------------------------------------------
# Экспорт bundle
# ---------------------------------------------------------------------------
def _feature_spec(model: Any, frame: Any) -> list[dict[str, Any]]:
    spec = []
    for c in model.features:
        if c in rt.CATEGORICAL:
            spec.append({"name": c, "kind": "categorical", "dtype": "string|null", "levels": model.levels[c]})
        else:
            spec.append({"name": c, "kind": "numeric", "dtype": "float32|null"})
    return spec


def _example_records(features: list[dict[str, Any]], as_of: str) -> list[dict[str, Any]]:
    """Синтетический пример (не реальные данные): одна подходящая строка, одна с превышенным порогом, одна не газовая."""
    base: dict[str, Any] = {"as_of_date": as_of, "ид_канала_данных": "EXAMPLE-CHANNEL-1", "request_id": "ex-1"}
    for f in features:
        base[f["name"]] = (f["levels"][0] if f["levels"] else None) if f["kind"] == "categorical" else 0.0
    base.update({"f_gas_n_7d": 120.0, "f_gas_last": 0.05, "f_gas_max_7d": 0.4})
    above = {**base, "ид_канала_данных": "EXAMPLE-CHANNEL-2", "request_id": "ex-2", "f_gas_last": 1.3}
    not_gas = {**base, "ид_канала_данных": "EXAMPLE-CHANNEL-3", "request_id": "ex-3", "f_gas_n_7d": 0.0,
               "f_gas_last": None, "f_gas_max_7d": None}
    return [base, above, not_gas]


def _versions() -> dict[str, str]:
    import lightgbm
    import pandas
    import polars
    import sklearn

    return {"numpy": np.__version__, "pandas": pandas.__version__, "lightgbm": lightgbm.__version__,
            "polars": polars.__version__, "scikit-learn(train only)": sklearn.__version__}


def _model_version(recipe: str, model_sha: str) -> str:
    return f"gas-cross-g2-v3-{recipe}-{model_sha[:12]}"


def _feature_contract_version(schema: Any, taxonomy_sha: Any, allowlist_sha: str) -> str:
    return f"event-panel-v{schema}+tax-{str(taxonomy_sha)[:8]}+g2-{allowlist_sha[:8]}"


def _contract(spec: dict[str, Any], features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"bundle_schema": BUNDLE_SCHEMA, "target_code": TARGET_CODE,
                "input": {"required": ["as_of_date (YYYY-MM-DD) — обязательна, иначе ContractError"],
                          "passthrough": ["ид_канала_данных", "request_id"],
                          "features": features, "n_features": len(features),
                          "unknown_fields": "ошибка контракта", "missing_features": "ошибка контракта",
                          "producer": "predictor.build_features(journal_files, catalogue_file, as_of_date, bundle) — код ноутбука 14",
                          "history_days_required": spec.get("history_days_required", HISTORY_DAYS_REQUIRED)},
                "model_version": spec["model_version"], "feature_contract_version": spec["feature_contract_version"],
                "output_fields": ["request_index", "as_of_date", "observation_cutoff_date", "ид_канала_данных", "request_id",
                                  "target_code", "model_version", "feature_contract_version", "evidence_level",
                                  "incident_type", "score", "raw_score", "score_kind", "decision_status", "reason_codes",
                                  "window_start", "window_end_exclusive", "evidence_scope", "operational_ready",
                                  "not_a_confirmed_incident", "not_fire_probability"],
                "eligibility": spec["eligibility"]}


def export_bundle(out_dir: Path, fit: dict[str, Any], manifest: dict[str, Any], manifest_path: Path,
                  cfg: dict[str, Any], audit: dict[str, Any], thr: float) -> Path:
    code_dir = Path(cfg["code_dir"])
    bdir = Path(out_dir) / BUNDLE_DIR_NAME
    if bdir.exists():
        shutil.rmtree(bdir)
    (bdir / "features_v3").mkdir(parents=True)
    model = fit["model"]
    booster = model.model.booster_
    model_txt = booster.model_to_string()
    (bdir / "model.txt").write_text(model_txt, encoding="utf-8")
    features = _feature_spec(model, fit["audit_all"])
    names = [f["name"] for f in features]
    if booster.feature_name() != names or booster.num_feature() != len(names):
        raise RuntimeError("признаки booster не совпадают с экспортируемым контрактом")
    allowlist = list(manifest["feature_columns"])
    recipe = RECIPES[cfg["recipe"]]
    iso = lambda d: d.isoformat()  # noqa: E731
    spec = {
        "bundle_schema": BUNDLE_SCHEMA, "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": cfg["mode"], "target": TARGET, "target_code": TARGET_CODE, "incident_type": "gas_threshold_cross",
        "model": MODEL_NAME, "model_format": "lightgbm_text", "model_sha256": _sha256_text(model_txt),
        "score_kind": "proxy_score", "decision_status": "experimental_shadow",
        # E1 — наблюдаемый в журнале proxy одного канала (шкала scorecard 12: E1/E2 proxy, E4 синтетика)
        "evidence_level": "E1", "evidence_level_meaning": "observed_journal_proxy_not_confirmed_incident",
        "model_version": _model_version(cfg["recipe"], _sha256_text(model_txt)),
        "feature_contract_version": _feature_contract_version(
            manifest.get("schema_version"), manifest.get("taxonomy_sha256"),
            _sha256_text(json.dumps(list(manifest["feature_columns"]), ensure_ascii=False))),
        "evidence_scope": "known_outcome_subset", "operational_ready": False,
        "meaning": ("score будущего наблюдаемого строгого пересечения газового порога 1 % снизу вверх в [D+2; D+3) "
                    "по данным до конца D; не вероятность пожара и не подтверждённый инцидент"),
        "window": {"start_offset_days": 2, "end_offset_days_exclusive": 3, "features_until": "end of day D"},
        "recipe": {"name": cfg["recipe"], "train": f"D < {iso(recipe['train_end'])}, d_label_decision_end ≤ {iso(recipe['calibration'][0])}",
                   "calibration": f"[{iso(recipe['calibration'][0])}; {iso(recipe['calibration'][1])}), decision_end ≤ {iso(recipe['audit'][0])}",
                   "audit": f"[{iso(recipe['audit'][0])}; {iso(recipe['audit'][1])}), decision_end ≤ {iso(recipe['audit'][1])}",
                   "excluded": f"[{iso(rt.EXCLUDED[0])}; {iso(rt.EXCLUDED[1])})",
                   "hyperparameters": {k: v for k, v in model.model.get_params().items()
                                       if k in ("n_estimators", "learning_rate", "num_leaves", "max_bin", "min_child_samples",
                                                "subsample", "subsample_freq", "colsample_bytree", "random_state")},
                   "negatives_per_positive": cfg["max_neg_per_pos"], "max_train_rows": cfg["max_train_rows"]},
        "counts": fit["counts"],
        "platt": {"coef": float(fit["platt"].coef_[0][0]), "intercept": float(fit["platt"].intercept_[0]),
                  "input": "logit(clip(raw, 1e-6, 1-1e-6))"},
        "features": features, "n_features": len(features),
        "feature_allowlist_sha256": _sha256_text(json.dumps(allowlist, ensure_ascii=False)),
        "eligibility": {"rule": "f_gas_n_7d > 0 and f_gas_last is not null and f_gas_last < gas_threshold_percent",
                        "gas_threshold_percent": thr,
                        "abstain_reasons": ["NOT_GAS_STREAM", "NO_GAS_READING_AT_D", "ABOVE_THRESHOLD_AT_D"]},
        "history_days_required": HISTORY_DAYS_REQUIRED,
        "panel_config": manifest.get("panel_config", {}),
        "panel": {"schema_version": manifest.get("schema_version"), "rows": manifest.get("rows"),
                  "manifest_sha256": _sha256_file(manifest_path), "taxonomy_sha256": manifest.get("taxonomy_sha256"),
                  "data_end": manifest.get("data_end"), "parts_sha256": [p["sha256"] for p in manifest.get("parts", [])]},
        "versions": _versions(),
        "backend_rules": ["автоматические заявки/критические уведомления по score выключены (shadow)",
                          "суточный бюджет top-k и cooldown 72 ч применяет backend; рекомендуемый shadow-бюджет 25/сутки",
                          "score разных целей не усредняются и не называются вероятностью инцидента",
                          "физической локации нет: показывать объект/канал, координаты — отсутствуют"],
    }
    (bdir / "bundle.json").write_text(_dump(spec), encoding="utf-8")
    shutil.copy(code_dir / "gas_predictor_v3.py", bdir / "predictor.py")
    shutil.copy(code_dir / "event_panel_v3.py", bdir / "features_v3" / "event_panel_v3.py")
    shutil.copy(code_dir / "config" / "state_taxonomy_v3.json", bdir / "features_v3" / "state_taxonomy_v3.json")
    contract = _contract(spec, features)
    (bdir / "feature_contract.json").write_text(_dump(contract), encoding="utf-8")
    example = _example_records(features, "2026-01-15")
    (bdir / "example_request.json").write_text(_dump(example), encoding="utf-8")
    v = spec["versions"]
    (bdir / "requirements.txt").write_text(
        f"numpy=={v['numpy']}\npandas=={v['pandas']}\nlightgbm=={v['lightgbm']}\n"
        f"# только для build_features (признаки из журнала):\npolars=={v['polars']}\n", encoding="utf-8")
    (bdir / "audit.json").write_text(_dump(audit), encoding="utf-8")
    (bdir / "README_RU.md").write_text(bundle_readme(spec, audit), encoding="utf-8")
    _pack(bdir, Path(out_dir))
    return bdir


def _pack(bdir: Path, out_dir: Path) -> Path:
    """SHA256SUMS.json по всем файлам каталога и ZIP (SHA-256 самого ZIP — отдельным файлом, не внутри)."""
    sums = {str(p.relative_to(bdir)): _sha256_file(p) for p in sorted(bdir.rglob("*")) if p.is_file()}
    (bdir / "SHA256SUMS.json").write_text(_dump(sums), encoding="utf-8")
    zpath = out_dir / f"{BUNDLE_DIR_NAME}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(bdir.rglob("*")):
            if p.is_file():
                z.write(p, Path(BUNDLE_DIR_NAME) / p.relative_to(bdir))
    return zpath


def bundle_readme(spec: dict[str, Any], audit: dict[str, Any]) -> str:
    g = audit.get("models", {}).get(MODEL_NAME, {})
    r = audit.get("models", {}).get("R1_rule", {})
    b25 = g.get("budget", {}).get("25", {})
    return "\n".join([
        f"# Газовый proxy v3 — bundle для backend ({spec['decision_status']})", "",
        spec["meaning"] + ".", "",
        "```python",
        "from predictor import load_bundle, build_features, predict",
        "bundle = load_bundle('.')",
        "records = build_features(['journal_extract.csv'], 'catalogue.csv', '2026-09-24', bundle)",
        "results = predict(records, bundle)",
        "```", "",
        f"- Рецепт: `{spec['recipe']['name']}`; train {spec['recipe']['train']}; калибровка {spec['recipe']['calibration']}.",
        f"- Признаков: {spec['n_features']} (список и типы — `feature_contract.json`); история журнала ≥ "
        f"{spec['history_days_required']} суток до D.",
        f"- Eligibility: {spec['eligibility']['rule']}; иначе `abstain` с причиной.",
        f"- Audit ({spec['recipe']['audit']}): PR-AUC G2 {_fmt(g.get('pr_auc'))} против правила {_fmt(r.get('pr_auc'))}; "
        f"25/сутки с cooldown: precision {_fmt(b25.get('precision_cooldown'))}–{_fmt(b25.get('precision_upper_cooldown'))}, "
        f"доля неизвестных исходов среди оповещений {_fmt(b25.get('alert_unknown_share_cooldown'))}.",
        "- `operational_ready = false`: автоматические заявки по score выключены; бюджет и cooldown — на backend.",
        "- Файлы: `model.txt` (LightGBM), `bundle.json` (калибровка, контракт), `predictor.py`, `features_v3/` (код "
        "признаков ноутбука 14 и таксономия), `SHA256SUMS.json`.", ""])


def _fmt(x: Any, d: int = 3) -> str:
    return "—" if x is None else f"{x:.{d}f}"


# ---------------------------------------------------------------------------
# Приёмка: bundle, загруженный из файлов, против модели в памяти (только агрегаты)
# ---------------------------------------------------------------------------
def _import_predictor(bundle_dir: Path) -> Any:
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("gas_bundle_predictor", Path(bundle_dir) / "predictor.py")
    module = importlib.util.module_from_spec(spec)
    flag, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # не оставлять __pycache__ в каталоге bundle
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = flag
    return module


def acceptance(bundle_dir: Path, fit: dict[str, Any], cfg: dict[str, Any], thr: float) -> dict[str, Any]:
    import tempfile

    import polars as pl

    pred = _import_predictor(bundle_dir)
    bundle = pred.load_bundle(bundle_dir)
    names = [f["name"] for f in bundle["spec"]["features"]]
    frame = fit["audit_all"]
    if frame.height > cfg["acceptance_rows"]:
        frame = frame.sample(n=cfg["acceptance_rows"], seed=cfg["random_seed"])
    rep: dict[str, Any] = {"rows_checked": frame.height}
    elig = runtime_eligible(frame, thr)
    sub = frame.filter(elig)
    records = sub.select([pl.col("d_cutoff_date").cast(pl.String).alias("as_of_date")] + names).to_pandas()
    res = pred.predict(records, bundle)
    raw_mem = fit["model"].score(sub)
    cal_mem = rt.apply_platt(fit["platt"], raw_mem, True, fit["prior"])
    raw_b = np.array([r["raw_score"] for r in res], dtype=float)
    cal_b = np.array([r["score"] for r in res], dtype=float)
    rep["max_abs_diff_raw"] = float(np.max(np.abs(raw_b - raw_mem))) if len(res) else 0.0
    rep["max_abs_diff_calibrated"] = float(np.max(np.abs(cal_b - cal_mem))) if len(res) else 0.0
    rep["parity_ok"] = rep["max_abs_diff_raw"] < 1e-9 and rep["max_abs_diff_calibrated"] < 1e-9
    rep["all_selectable_rows_runtime_eligible"] = bool(elig.all())
    ex = json.loads((Path(bundle_dir) / "example_request.json").read_text(encoding="utf-8"))
    out = pred.predict(ex, bundle)
    rep["example_statuses"] = [o["decision_status"] + ":" + ",".join(o["reason_codes"]) for o in out]
    rep["example_ok"] = (out[0]["decision_status"] == "experimental_shadow" and out[0]["score"] is not None
                         and out[1]["reason_codes"] == ["ABOVE_THRESHOLD_AT_D"] and out[2]["reason_codes"] == ["NOT_GAS_STREAM"])
    bad = dict(ex[0])
    bad.pop(names[0])
    try:
        pred.predict([bad], bundle)
        rep["missing_feature_rejected"] = False
    except pred.ContractError:
        rep["missing_feature_rejected"] = True
    try:
        pred.predict([{**ex[0], "target_t4_gas_cross": 1}], bundle)
        rep["unknown_field_rejected"] = False
    except pred.ContractError:
        rep["unknown_field_rejected"] = True
    no_date = {k: v for k, v in ex[0].items() if k != "as_of_date"}
    for key, rec in (("missing_as_of_rejected", no_date), ("bad_as_of_rejected", {**ex[0], "as_of_date": "25.09.2026"})):
        try:
            pred.predict([rec], bundle)
            rep[key] = False
        except pred.ContractError:
            rep[key] = True
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "b"
        shutil.copytree(bundle_dir, copy)
        with open(copy / "features_v3" / "state_taxonomy_v3.json", "a", encoding="utf-8") as f:
            f.write(" ")
        try:
            pred.load_bundle(copy)
            rep["tampered_file_rejected"] = False
        except pred.ContractError:
            rep["tampered_file_rejected"] = True
    o = out[0]
    rep["typed_fields_present"] = all(o.get(k) for k in ("model_version", "feature_contract_version", "evidence_level",
                                                           "observation_cutoff_date", "window_start"))
    cat = next((f["name"] for f in bundle["spec"]["features"] if f["kind"] == "categorical"), None)
    if cat:
        o = pred.predict([{**ex[0], cat: "никогда-не-встречавшийся-уровень"}], bundle)[0]
        rep["unknown_category_scored"] = o["score"] is not None
    nulls = {**ex[0], **{n: None for n in names if n not in ("f_gas_n_7d", "f_gas_last")}}
    rep["null_features_scored"] = pred.predict([nulls], bundle)[0]["score"] is not None
    big = records.sample(n=cfg["latency_rows"], replace=True, random_state=0) if len(records) else records
    t0 = time.time()
    if len(big):
        pred.predict(big, bundle)
    rep["latency_rows"] = int(len(big))
    rep["latency_s"] = round(time.time() - t0, 2)
    rep["latency_ok"] = rep["latency_s"] < cfg["latency_budget_s"]
    rep["passed"] = all(v for k, v in rep.items() if isinstance(v, bool))
    return rep


# ---------------------------------------------------------------------------
# Воспроизведение 15 (не участвует в выборе: рецепт и модель уже зафиксированы)
# ---------------------------------------------------------------------------
def reproduce_15(pl: Any, frame: Any, feats: list[str], cfg: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    """PR-AUC G2 на валидации fold_2024 тем же кодом, что в экспорте, против числа из results_15_v3.json.
    Для fold_2024_exact это сам audit; для refit — отдельное обучение fold_2024 только ради сверки."""
    from sklearn.metrics import average_precision_score

    expected = cfg.get("expected_15_fold_2024_pr_auc")
    if cfg["recipe"] == "fold_2024_exact":
        got = audit.get("models", {}).get(MODEL_NAME, {}).get("pr_auc")
    else:
        fold = next(f for f in rt.FOLDS if f["name"] == "fold_2024")
        train, _, val = rt.split_fold(pl, frame, fold)
        known = pl.col(TARGET).is_not_null()
        train, val = train.filter(known), val.filter(known)
        if train.height == 0 or val.height == 0 or val[TARGET].n_unique() < 2:
            return {"expected": expected, "got": None, "status": "not_applicable"}
        m = rt.LightGBM().fit(rt.sample_train(pl, train, TARGET, cfg), TARGET, feats, cfg)
        got = float(average_precision_score(val[TARGET].to_numpy().astype(int), m.score(val)))
    rep = {"expected": expected, "got": got}
    if expected is None or got is None:
        rep["status"] = "not_checked"
    else:
        rep["abs_diff"] = abs(got - expected)
        rep["status"] = "reproduced" if rep["abs_diff"] <= cfg["reproduction_tolerance"] else "MISMATCH"
    return rep


# ---------------------------------------------------------------------------
# Прогон
# ---------------------------------------------------------------------------
def run_export_v3(cfg: dict[str, Any], log: Any = print) -> dict[str, Any]:
    import polars as pl

    t_start = time.time()
    out = Path(cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    parts, manifest = rt.discover_panel(Path(cfg["input_dir"]), cfg["verify_sha256"])
    manifest_path = sorted(Path(cfg["input_dir"]).rglob("panel_manifest_v3.json"))[0]
    thr = float(manifest.get("panel_config", {}).get("gas_threshold_percent", 1.0))
    columns = pl.scan_parquet(parts[0]).collect_schema().names()
    feats = g2_features(manifest, columns)
    log(f"панель: {manifest['rows']:,} строк, частей {len(parts)}; признаков G2: {len(feats)}; порог газа {thr}")
    recipe = RECIPES[cfg["recipe"]]
    frame = rt.load_target(pl, parts, TARGET, feats, cfg, load_end=recipe["audit"][1])
    log(f"selectable строк цели до {recipe['audit'][1]}: {frame.height:,}")
    payload: dict[str, Any] = {"recipe": cfg["recipe"], "target": TARGET, "model": MODEL_NAME, "n_features": len(feats)}

    def finish(status: str) -> dict[str, Any]:
        payload.update({"status": status, "runtime_s": round(time.time() - t_start, 1)})
        (out / "results_export_16_v3.json").write_text(_dump(payload), encoding="utf-8")
        (out / "summary_export_16_v3_ru.md").write_text(summary_markdown(payload), encoding="utf-8")
        return payload

    def check_repro(repro: dict[str, Any]) -> None:
        payload["reproduction_15"] = repro
        log(f"сверка с 15 (G2 fold_2024 PR-AUC): ожидалось {repro.get('expected')}, получено {repro.get('got')} — {repro['status']}")
        if repro["status"] == "MISMATCH":   # fail-closed (GPT 29): bundle не собирается, рецепт не меняется
            finish("reproduction_mismatch")
            raise ReleaseBlocked(f"код обучения не воспроизводит G2 из 15: {repro}. Bundle не создан.")

    if cfg["recipe"] != "fold_2024_exact":
        # сверочное обучение fold_2024 (второй fit, в выборе не участвует) — до финального, чтобы остановиться рано
        check_repro(reproduce_15(pl, frame, feats, cfg, {}))
    fit = train_final(pl, frame, feats, cfg, log)
    audit = audit_final(pl, fit, cfg, thr)
    payload.update({"counts": fit["counts"], "calibration_ece10": fit["calibration_ece10"],
                    "calibration_prevalence": fit["calibration_prevalence"], "audit": audit})
    if cfg["recipe"] == "fold_2024_exact":
        check_repro(reproduce_15(pl, frame, feats, cfg, audit))
    bdir = export_bundle(out, fit, manifest, manifest_path, cfg, audit, thr)
    acc = acceptance(bdir, fit, cfg, thr)
    payload["acceptance"] = acc
    zpath = out / f"{BUNDLE_DIR_NAME}.zip"
    if not acc["passed"]:                   # fail-closed: непринятый bundle не остаётся в Output
        shutil.rmtree(bdir, ignore_errors=True)
        zpath.unlink(missing_ok=True)
        finish("acceptance_failed")
        raise ReleaseBlocked(f"приёмка bundle не пройдена: {acc}. Bundle удалён.")
    zsha = _sha256_file(zpath)
    (out / f"{BUNDLE_DIR_NAME}.zip.sha256").write_text(f"{zsha}  {zpath.name}\n", encoding="utf-8")
    payload.update({"bundle_zip": zpath.name, "bundle_zip_sha256": zsha,
                    "model_version": json.loads((bdir / "bundle.json").read_text(encoding="utf-8"))["model_version"]})
    return finish("completed_smoke_non_comparable" if cfg["mode"] == "SMOKE" else "completed")


def summary_markdown(p: dict[str, Any]) -> str:
    if "counts" not in p:
        rp = p.get("reproduction_15", {})
        return (f"# 16 · Финальный газовый bundle v3 — {p['status']}\n\nОстановлено до финального обучения: сверка с 15 "
                f"(G2 fold_2024 PR-AUC) ожидалось {_fmt(rp.get('expected'), 4)}, получено {_fmt(rp.get('got'), 4)}. "
                "Bundle не создан; рецепт автоматически не меняется.\n")
    a = p["audit"]
    g = a.get("models", {}).get(MODEL_NAME, {})
    r = a.get("models", {}).get("R1_rule", {})
    c = p["counts"]
    L = [f"# 16 · Финальный газовый bundle v3 — {p['status']}", "",
         f"Рецепт **{p['recipe']}**, модель {MODEL_NAME}, признаков {p['n_features']}. "
         "Цель — наблюдаемое пересечение газа 1 % в D+2 (proxy), не вероятность пожара.", "",
         f"- train: {c['train']:,} строк (1: {c['train_pos']:,}), в обучение после выборки {c.get('train_sampled', 0):,};",
         f"- калибровка: {c['calibration']:,} (1: {c['calibration_pos']:,}), ECE-10 на ней {p['calibration_ece10']:.4f};",
         f"- audit: selectable {a.get('rows_selectable', 0):,}, известен исход {a.get('rows_known', 0):,} "
         f"(доля неизвестных {_fmt(a.get('unknown_share_selectable'))}), положительных {a.get('positives_known', 0):,};",
         f"- runtime eligibility покрывает selectable строки audit: {_fmt(a.get('runtime_eligible_share_of_selectable'), 4)} (ожидается 1).", "",
         "## Audit (однократно, ничего не выбирает)", "",
         f"PR-AUC G2 {_fmt(g.get('pr_auc'))} против правила R1 {_fmt(r.get('pr_auc'))}; ROC-AUC {_fmt(g.get('roc_auc'))}; "
         f"Brier {_fmt(g.get('brier'), 4)}, ECE-10 {_fmt(g.get('ece10'), 4)}.", "",
         "| k/сутки | модель | precision (cooldown), границы | recall (cooldown), границы | оповещений | доля unknown среди них |",
         "|---|---|---|---|---|---|"]
    for k in (str(x) for x in (5, 10, 25, 50)):
        for name, m in ((MODEL_NAME, g), ("R1_rule", r)):
            b = m.get("budget", {}).get(k)
            if b:
                L.append(f"| {k} | {name} | {_fmt(b['precision_cooldown'])}–{_fmt(b['precision_upper_cooldown'])} | "
                         f"{_fmt(b['recall_low_cooldown'])}–{_fmt(b['recall_up_cooldown'])} | {b['alerts_cooldown']:,} | "
                         f"{_fmt(b['alert_unknown_share_cooldown'])} |")
    acc = p.get("acceptance")
    rp = p.get("reproduction_15", {})
    L += ["", "## Сверка с ноутбуком 15", "",
          f"PR-AUC G2 на валидации fold_2024: в 15 {_fmt(rp.get('expected'), 4)}, код экспорта {_fmt(rp.get('got'), 4)} — "
          f"**{rp.get('status')}** (в выборе не участвует; MISMATCH — bundle не создаётся)."]
    if acc is None:
        L += ["", f"Bundle не создан: статус {p['status']}.", ""]
        return "\n".join(L)
    L += ["", "## Приёмка bundle", "",
          f"- parity (bundle из файлов против модели в памяти): raw {acc['max_abs_diff_raw']:.2e}, "
          f"калиброванный {acc['max_abs_diff_calibrated']:.2e} — {'OK' if acc['parity_ok'] else 'FAIL'};",
          f"- пример: {', '.join(acc['example_statuses'])} — {'OK' if acc['example_ok'] else 'FAIL'};",
          f"- контракт: нет признака → ошибка {acc['missing_feature_rejected']}, лишнее поле → ошибка {acc['unknown_field_rejected']}, "
          f"неизвестная категория → score {acc.get('unknown_category_scored')}, null-признаки → score {acc['null_features_scored']};",
          f"- latency: {acc['latency_rows']:,} строк за {acc['latency_s']} с — {'OK' if acc['latency_ok'] else 'FAIL'}.", "",
          f"- проверка SHA всех файлов при загрузке, отказ без as_of_date / с битой датой: "
          f"{acc.get('tampered_file_rejected')} / {acc.get('missing_as_of_rejected')} / {acc.get('bad_as_of_rejected')}.", "",
          "Ключей каналов и построчных прогнозов в этих файлах нет. Bundle: `" + p.get("bundle_zip", "—") + "`, "
          f"SHA-256 ZIP `{p.get('bundle_zip_sha256', '—')}` (в `{BUNDLE_DIR_NAME}.zip.sha256`), "
          f"model_version `{p.get('model_version', '—')}`.", ""]
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Самопроверки на синтетике (запускаются в ноутбуке до прогона)
# ---------------------------------------------------------------------------
def run_export_self_tests(work_dir: Path) -> dict[str, bool]:
    work_dir = Path(work_dir)
    rep: dict[str, bool] = {}
    root = work_dir / "synthetic_in"
    rt.synthetic_panel_v3(root, n_channels=80, end=date(2026, 1, 10), gas_features=True)
    for recipe in RECIPES:
        cfg = make_config_export("SMOKE", recipe, {"input_dir": str(root), "output_dir": str(work_dir / recipe),
                                                   "smoke_channel_share": 1, "latency_rows": 2000,
                                                   "min_calibration_positives": 5, "min_train_positives": 5})
        res = run_export_v3(cfg, log=lambda *a: None)
        rep[f"{recipe}_acceptance_passed"] = res["acceptance"]["passed"]
        text = (work_dir / recipe / "results_export_16_v3.json").read_text(encoding="utf-8")
        import polars as pl

        keys = pl.read_parquet(root / "event_panel_v3" / "event_panel_v3_part00.parquet")["d_channel_key"].unique().to_list()
        rep[f"{recipe}_no_channel_keys_in_results"] = not any(k in text for k in keys)
    cfg = make_config_export("SMOKE", "refit_2025h1", {"input_dir": str(root), "output_dir": str(work_dir / "stop"),
                                                       "smoke_channel_share": 1, "min_calibration_positives": 10**9})
    try:
        run_export_v3(cfg, log=lambda *a: None)
        rep["too_few_calibration_positives_stops_before_training"] = False
    except RecipeStop:
        rep["too_few_calibration_positives_stops_before_training"] = not (work_dir / "stop" / BUNDLE_DIR_NAME).exists()
    return rep


# ---------------------------------------------------------------------------
# Переупаковка bundle первой версии 16 (без release gates) — без обучения
# ---------------------------------------------------------------------------
def repack_bundle(old_dir: Path, out_dir: Path, code_dir: Path | None = None) -> Path:
    """Тот же model.txt, Platt, признаки и audit; новый predictor.py (обязательная дата, SHA всех файлов, история),
    typed-поля (model_version, feature_contract_version, evidence_level, observation_cutoff_date), новые
    SHA256SUMS, ZIP и .sha256. Обучения нет: model_sha256 не меняется."""
    old_dir, out_dir = Path(old_dir), Path(out_dir)
    code_dir = Path(code_dir) if code_dir else Path(__file__).resolve().parent
    sums = json.loads((old_dir / "SHA256SUMS.json").read_text(encoding="utf-8"))
    bad = [n for n, sha in sums.items() if _sha256_file(old_dir / n) != sha]
    if bad:
        raise RuntimeError(f"исходный bundle повреждён: {bad}")
    out_dir.mkdir(parents=True, exist_ok=True)
    bdir = out_dir / BUNDLE_DIR_NAME
    if bdir.exists():
        shutil.rmtree(bdir)
    shutil.copytree(old_dir, bdir, ignore=shutil.ignore_patterns("__pycache__"))
    spec = json.loads((bdir / "bundle.json").read_text(encoding="utf-8"))
    if _sha256_file(bdir / "model.txt") != spec["model_sha256"]:
        raise RuntimeError("model.txt не совпадает с bundle.json")
    spec.update({
        "evidence_level": "E1", "evidence_level_meaning": "observed_journal_proxy_not_confirmed_incident",
        "model_version": _model_version(spec["recipe"]["name"], spec["model_sha256"]),
        "feature_contract_version": _feature_contract_version(spec["panel"]["schema_version"], spec["panel"]["taxonomy_sha256"],
                                                              spec["feature_allowlist_sha256"]),
        "repack": {"at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "reason": "release gates GPT 29/30 без переобучения: predictor, typed-поля, SHA всех файлов",
                   "source_bundle_sha256sums_sha256": _sha256_file(old_dir / "SHA256SUMS.json"),
                   "model_retrained": False},
    })
    (bdir / "bundle.json").write_text(_dump(spec), encoding="utf-8")
    shutil.copy(code_dir / "gas_predictor_v3.py", bdir / "predictor.py")
    shutil.copy(code_dir / "event_panel_v3.py", bdir / "features_v3" / "event_panel_v3.py")
    (bdir / "feature_contract.json").write_text(_dump(_contract(spec, spec["features"])), encoding="utf-8")
    audit = json.loads((bdir / "audit.json").read_text(encoding="utf-8"))
    (bdir / "README_RU.md").write_text(bundle_readme(spec, audit), encoding="utf-8")
    (bdir / "SHA256SUMS.json").unlink()
    zpath = _pack(bdir, out_dir)
    (out_dir / f"{BUNDLE_DIR_NAME}.zip.sha256").write_text(f"{_sha256_file(zpath)}  {zpath.name}\n", encoding="utf-8")
    return bdir


def verify_repack(new_dir: Path, old_dir: Path, n: int = 5000, seed: int = 0) -> dict[str, Any]:
    """Новый predictor на переупакованном bundle против старого predictor на исходном: те же скоры на синтетических
    записях (реальных строк не нужно), плюс проверки контракта. Только агрегаты."""
    import pandas as pd

    old = _import_predictor(old_dir)
    new = _import_predictor(new_dir)
    b_old = old.load_bundle(old_dir)
    b_new = new.load_bundle(new_dir)
    rng = np.random.default_rng(seed)
    rows = {}
    for f in b_new["spec"]["features"]:
        if f["kind"] == "categorical":
            lv = list(f["levels"]) + [None]
            rows[f["name"]] = [lv[i] for i in rng.integers(0, len(lv), n)]
        else:
            v = np.abs(rng.normal(0, 3, n)) * rng.choice([0.0, 1.0, 10.0], n)
            v[rng.random(n) < 0.05] = np.nan
            rows[f["name"]] = v
    rows["f_gas_n_7d"] = rng.integers(0, 50, n).astype(float)
    rows["f_gas_last"] = rng.uniform(0, 1.3, n)
    frame = pd.DataFrame(rows)
    frame.insert(0, "as_of_date", "2026-01-15")
    a = old.predict(frame, b_old)
    b = new.predict(frame, b_new)
    sa = np.array([np.nan if r["score"] is None else r["score"] for r in a])
    sb = np.array([np.nan if r["score"] is None else r["score"] for r in b])
    rep: dict[str, Any] = {"records": n, "scored": int((~np.isnan(sb)).sum()),
                           "same_abstain": bool(np.array_equal(np.isnan(sa), np.isnan(sb))),
                           "max_abs_diff_score": float(np.nanmax(np.abs(sa - sb))) if (~np.isnan(sb)).any() else 0.0,
                           "same_model_sha": b_old["spec"]["model_sha256"] == b_new["spec"]["model_sha256"]}
    rep["scores_identical"] = rep["same_abstain"] and rep["max_abs_diff_score"] == 0.0
    ex = json.loads((Path(new_dir) / "example_request.json").read_text(encoding="utf-8"))
    o = new.predict(ex, b_new)
    rep["example_ok"] = (o[0]["decision_status"] == "experimental_shadow" and o[1]["reason_codes"] == ["ABOVE_THRESHOLD_AT_D"]
                         and o[2]["reason_codes"] == ["NOT_GAS_STREAM"])
    rep["typed_fields_present"] = all(o[0].get(k) for k in ("model_version", "feature_contract_version", "evidence_level",
                                                              "observation_cutoff_date"))
    for key, rec in (("missing_as_of_rejected", {k: v for k, v in ex[0].items() if k != "as_of_date"}),
                     ("bad_as_of_rejected", {**ex[0], "as_of_date": "15.01.2026"})):
        try:
            new.predict([rec], b_new)
            rep[key] = False
        except new.ContractError:
            rep[key] = True
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "b"
        shutil.copytree(new_dir, copy)
        with open(copy / "features_v3" / "state_taxonomy_v3.json", "a", encoding="utf-8") as f:
            f.write(" ")
        try:
            new.load_bundle(copy)
            rep["tampered_file_rejected"] = False
        except new.ContractError:
            rep["tampered_file_rejected"] = True
    rep["passed"] = all(v for k, v in rep.items() if isinstance(v, bool))
    return rep
