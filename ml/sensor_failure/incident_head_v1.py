"""Модуль прогноза инцидентов по реестру (incident_head v1, ноутбук 18).

Контракт: docs/INCIDENT_REGISTER_CONTRACT_RU.md.
- Вход: панель v3 (выход 14) + реестр подтверждённых инцидентов с файлом покрытия. Пока реального реестра нет,
  используется ЗАГЛУШКА (label_source = "stub", evidence_level = E4); реальный реестр подключается тем же кодом.
- Цель на (объект, D) для типа k: 1 — подтверждённый инцидент типа k начался в [D+2; D+3); 0 — в покрытии и нет;
  null — вне покрытия или инцидент того же типа начался в [D−6; D].
- Признаки: агрегация канальных v3-векторов до объекта (incident_predictor_v1.aggregate_objects — тот же код в bundle).
- Модель: LightGBM + Platt, разбиение по времени; заранее заданные пороги допуска; baseline — prevalence и правило
  «профильные тревоги за 7 суток»; кривая обучения по числу положительных.

Заглушка: инцидент типа k разыгрывается по реальным суткам X объекта, logit = a + β·z(log1p(след_k(X))), где след —
профильные тревоги объекта в сами сутки X; плюс доля инцидентов без следа. Модель видит только данные ≤ D = X − 2,
поэтому измеряется предсказуемость будущего всплеска профильной активности, а не рецепт генератора.
β: 0 (контроль — качество обязано быть на уровне случайного), 1 (слабая), 2 (средняя, основная для bundle), 3 (сильная:
настоящий пожар или затопление почти всегда даёт срабатывания профильных датчиков). Всё задано до запуска на реальных данных.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

import incident_predictor_v1 as ip
import target_models_v3_runtime as rt

MODULE_DIR = Path(__file__).resolve().parent
SCENARIOS = {"control": 0.0, "weak": 1.0, "medium": 2.0, "strong": 3.0}
MAIN_SCENARIO = "medium"
PANEL_START = date(2022, 1, 31)       # как в 15/16: 2021 и прогрев окон исключены
REGISTER_COLUMNS = ["ид_инцидента", "тип_инцидента", "начало", "подтверждён"]
STUB_GENERATOR_VERSION = "stub-trace-v1"


def make_config_18(mode: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = rt.make_config_targets(mode)
    cfg.update({
        "scenarios": dict(SCENARIOS), "main_scenario": MAIN_SCENARIO,
        "rate_per_object_year": 1.0, "no_trace_share": 0.3, "stub_seed": 18,
        "stub_period": (PANEL_START, date(2026, 1, 1)),
        "train_end": date(2025, 1, 1), "cal_end": date(2025, 7, 1), "test_end": date(2026, 1, 1),
        "min_train_positives": 30, "min_calibration_positives": 30, "min_test_positives": 10,
        "budget_objects_per_day": 10, "cooldown_days": 3,
        "learning_curve_sizes": [25, 50, 100, 200],
        "smoke_object_share": 4,
        "register_path": None, "coverage_path": None,
    })
    cfg.update(overrides or {})
    return cfg


def _sha256_file(path: Path) -> str:
    return rt.file_sha256(Path(path))


def _jd(o: Any) -> Any:
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(type(o).__name__)


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=_jd)


# ---------------------------------------------------------------------------
# Объектная панель
# ---------------------------------------------------------------------------
def build_object_panel(pl: Any, parts: list[Path], cfg: dict[str, Any]) -> Any:
    lf = pl.scan_parquet(parts)
    cols = lf.collect_schema().names()
    need = set(ip.CHANNEL_SUM + ip.GROUP_COLS + ["link_state", "power_state", "gas_max", "f_gas_max_7d",
                                                "тип_датчика", "d_object_key", "d_cutoff_date"])
    lf = lf.select([c for c in cols if c in need]).filter(
        (pl.col("d_cutoff_date") >= cfg["stub_period"][0]) & (pl.col("d_cutoff_date") < cfg["test_end"] + timedelta(days=3)))
    if cfg["mode"] == "SMOKE":
        lf = lf.filter(pl.col("d_object_key").hash(seed=7) % cfg["smoke_object_share"] == 0)
    return ip.aggregate_objects(pl, lf, object_col="d_object_key").collect().sort("object_ref", "d_cutoff_date")


# ---------------------------------------------------------------------------
# Реестр: заглушка и загрузка
# ---------------------------------------------------------------------------
def _solve_intercept(z: np.ndarray, beta: float, target: float) -> float:
    lo, hi = -40.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if np.mean(1 / (1 + np.exp(-(mid + beta * z)))) > target:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def make_stub_register(pl: Any, obj: Any, cfg: dict[str, Any], beta: float, seed: int) -> tuple[Any, dict[str, Any]]:
    """Заглушка реестра на реальных сутках объектов. Возвращает (реестр, покрытие)."""
    start, end = cfg["stub_period"]
    fr = obj.filter((pl.col("d_cutoff_date") >= start) & (pl.col("d_cutoff_date") < end))
    rng = np.random.default_rng(seed)
    r = cfg["rate_per_object_year"] / 365.0
    s = cfg["no_trace_share"]
    rows: dict[str, list[Any]] = {"ид_инцидента": [], "d_object_key": [], "тип_инцидента": [], "начало": [],
                                  "окончание": [], "подтверждён": [], "источник": []}
    for kind in ip.GROUPS:
        x = np.log1p(fr[f"_fp_{kind}"].fill_null(0).to_numpy().astype(float))
        z = (x - x.mean()) / x.std() if x.std() > 0 else np.zeros_like(x)
        a = _solve_intercept(z, beta, r)
        p = (1 - s) / (1 + np.exp(-(a + beta * z))) + s * r
        hit = np.flatnonzero(rng.random(len(p)) < p)
        refs, days = fr["object_ref"].to_numpy()[hit], fr["d_cutoff_date"].to_numpy()[hit]
        hours = rng.integers(0, 24, len(hit))
        for i, (o, d, h) in enumerate(zip(refs, days, hours)):
            t0 = datetime.combine(date.fromisoformat(str(d)[:10]), datetime.min.time()) + timedelta(hours=int(h))
            rows["ид_инцидента"].append(f"stub-{kind}-{i:06d}")
            rows["d_object_key"].append(str(o))
            rows["тип_инцидента"].append(ip.TYPE_RU[kind])
            rows["начало"].append(t0.isoformat())
            rows["окончание"].append((t0 + timedelta(hours=6)).isoformat())
            rows["подтверждён"].append(True)
            rows["источник"].append("stub")
    reg = pl.DataFrame(rows, schema={k: (pl.Boolean if k == "подтверждён" else pl.String) for k in rows})
    coverage = {"period_start": start.isoformat(), "period_end_exclusive": end.isoformat(), "objects": "all",
                "incident_types": list(ip.INCIDENT_TYPES), "label_source": "stub",
                "stub": {"generator_version": STUB_GENERATOR_VERSION, "beta": beta,
                         "rate_per_object_year": cfg["rate_per_object_year"],
                         "no_trace_share": s, "seed": seed}}
    return reg, coverage


def validate_coverage(coverage: dict[str, Any]) -> dict[str, Any]:
    for k in ("period_start", "period_end_exclusive", "objects", "label_source"):
        if k not in coverage:
            raise ValueError(f"в покрытии нет поля {k}")
    if coverage["label_source"] not in ("register", "stub"):
        raise ValueError("label_source должен быть register или stub")
    return coverage


def _object_key(pl: Any, reg: Any) -> Any:
    if "d_object_key" in reg.columns:
        return reg.with_columns(pl.col("d_object_key").cast(pl.String).alias("object_ref"))
    if "ид_объект" not in reg.columns:
        raise ValueError("в реестре нет ид_объект")
    sys.path.insert(0, str(MODULE_DIR))
    import event_panel_v3 as ep  # псевдонимы как в панели 14

    return reg.with_columns(pl.col("ид_объект").cast(pl.String).map_elements(ep.pseudo_key, return_dtype=pl.String)
                            .alias("object_ref"))


def load_register(pl: Any, reg: Any, coverage: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    """Реестр → события (object_ref, day, kind); только подтверждённые, только три типа ТЗ."""
    validate_coverage(coverage)
    miss = [c for c in REGISTER_COLUMNS if c not in reg.columns]
    if miss:
        raise ValueError(f"в реестре нет колонок {miss}")
    reg = _object_key(pl, reg)
    ev = (reg.filter(pl.col("подтверждён").cast(pl.Boolean) & pl.col("тип_инцидента").is_in(list(ip.INCIDENT_TYPES)))
          .select("object_ref", pl.col("начало").cast(pl.String).str.slice(0, 10).str.to_date().alias("day"),
                  pl.col("тип_инцидента").replace_strict(ip.INCIDENT_TYPES).alias("kind"))
          .unique())
    stats = {"rows": reg.height, "confirmed_in_scope": ev.height,
             "by_type": {k: int((ev["kind"] == k).sum()) for k in ip.GROUPS}}
    return ev, stats


# ---------------------------------------------------------------------------
# Цели
# ---------------------------------------------------------------------------
def _flag(pl: Any, frame: Any, days: Any, offset: int) -> np.ndarray:
    key = frame.select(pl.int_range(0, pl.len(), dtype=pl.UInt32).alias("_row"), "object_ref",
                       (pl.col("d_cutoff_date") + pl.duration(days=offset)).alias("day"))
    hits = key.join(days.select("object_ref", "day").unique(), on=["object_ref", "day"], how="semi")["_row"].to_numpy()
    out = np.zeros(frame.height, dtype=bool)
    out[hits] = True
    return out


def build_targets(pl: Any, obj: Any, events: Any, coverage: dict[str, Any]) -> Any:
    start = date.fromisoformat(coverage["period_start"])
    end = date.fromisoformat(coverage["period_end_exclusive"])
    d2 = obj["d_cutoff_date"].to_numpy() + np.timedelta64(2, "D")
    in_cov = (d2 >= np.datetime64(start)) & (d2 < np.datetime64(end))
    if coverage["objects"] != "all":
        tmp = pl.DataFrame({"object_ref": [str(o) for o in coverage["objects"]]})
        if coverage.get("objects_are_raw_ids", True) and coverage["label_source"] == "register":
            tmp = _object_key(pl, tmp.rename({"object_ref": "ид_объект"}))
        in_cov &= obj["object_ref"].is_in(tmp["object_ref"]).to_numpy()
    cols = {}
    for kind in ip.GROUPS:
        ev = events.filter(pl.col("kind") == kind)
        pos = _flag(pl, obj, ev, 2)
        ongoing = np.zeros(obj.height, dtype=bool)
        for lag in range(0, 7):                              # начало в [D−6; D] ⇔ day + lag == D
            ongoing |= _flag(pl, obj, ev, -lag)
        competing = _flag(pl, obj, ev, 1) & ~pos             # начало того же типа в D+1: событие до окна D+2 (GPT 51)
        y = np.where(pos, 1.0, 0.0)
        y = np.where(~in_cov | ongoing | competing, np.nan, y)
        cols[f"target_{kind}"] = y
        cols[f"reason_{kind}"] = np.where(~in_cov, "outside_coverage", np.where(ongoing, "ongoing_incident", np.where(
            competing, "competing_event_d1", np.where(pos, "positive", "negative"))))
    return obj.with_columns([pl.Series(k, v, nan_to_null=True) if k.startswith("target_") else pl.Series(k, v)
                             for k, v in cols.items()])


def split(pl: Any, frame: Any, cfg: dict[str, Any]) -> tuple[Any, Any, Any]:
    """Разбиение по времени; окно исхода D+2 не пересекает границу периода."""
    d2 = pl.col("d_cutoff_date") + pl.duration(days=2)
    lo = cfg["stub_period"][0] if cfg.get("register_path") is None else frame["d_cutoff_date"].min()
    tr = frame.filter((pl.col("d_cutoff_date") >= lo) & (d2 < cfg["train_end"]))
    ca = frame.filter((pl.col("d_cutoff_date") >= cfg["train_end"]) & (d2 < cfg["cal_end"]))
    te = frame.filter((pl.col("d_cutoff_date") >= cfg["cal_end"]) & (d2 < cfg["test_end"]))
    return tr, ca, te


# ---------------------------------------------------------------------------
# Обучение одного типа
# ---------------------------------------------------------------------------
def _lr_params(m: Any) -> dict[str, float] | None:
    return None if m is None else {"coef": float(m.coef_[0][0]), "intercept": float(m.intercept_[0])}


def fit_type(pl: Any, tr: Any, ca: Any, te: Any, kind: str, feats: list[str], cfg: dict[str, Any],
             n_pos: int | None = None, seed: int = 0, full: bool = True) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score

    tgt = f"target_{kind}"
    known = pl.col(tgt).is_not_null()
    tr, ca, te = tr.filter(known), ca.filter(known), te.filter(known)
    counts = {"train": tr.height, "train_pos": int(tr[tgt].sum() or 0), "calibration": ca.height,
              "calibration_pos": int(ca[tgt].sum() or 0), "test": te.height, "test_pos": int(te[tgt].sum() or 0)}
    res: dict[str, Any] = {"counts": counts}
    if counts["train_pos"] < cfg["min_train_positives"] or counts["calibration_pos"] < cfg["min_calibration_positives"]:
        res["gate"] = "insufficient_labels"
        return res
    if n_pos is not None:
        if n_pos >= counts["train_pos"]:
            return {"counts": counts, "gate": "skipped_size"}
        pos_idx = np.flatnonzero(tr[tgt].to_numpy() == 1)
        keep = np.random.default_rng(seed).choice(pos_idx, n_pos, replace=False)
        mask = tr[tgt].to_numpy() == 0
        mask[keep] = True
        tr = tr.filter(pl.Series(mask))
    tr_s = rt.sample_train(pl, tr, tgt, cfg)
    model = rt.LightGBM().fit(tr_s, tgt, feats, cfg)
    y_ca, y_te = ca[tgt].to_numpy().astype(int), te[tgt].to_numpy().astype(int)
    p_model = rt.platt(model.score(ca), y_ca, True)
    p_rule = rt.platt(ip.rule_raw(ca, kind), y_ca, False)
    raw_te = model.score(te)
    s_model = rt.apply_platt(p_model, raw_te, True, float(y_ca.mean()))
    s_rule = rt.apply_platt(p_rule, ip.rule_raw(te, kind), False, float(y_ca.mean()))
    prev = float(y_te.mean()) if len(y_te) else None
    ok = counts["test_pos"] >= cfg["min_test_positives"] and 0 < y_te.sum() < len(y_te)
    m: dict[str, Any] = {"prevalence": prev}
    if ok:
        m.update({"pr_auc_model": float(average_precision_score(y_te, raw_te)),
                  "pr_auc_rule": float(average_precision_score(y_te, s_rule))})
        m["lift_model"], m["lift_rule"] = m["pr_auc_model"] / prev, m["pr_auc_rule"] / prev
    res.update({"n_pos_used": n_pos, "test_metrics": m})
    if not full:
        return res
    days = np.array([(d - date(2019, 1, 1)).days for d in te["d_cutoff_date"].to_list()])
    refs = te["object_ref"].to_numpy()
    if ok:
        m.update({"brier_model": float(np.mean((s_model - y_te) ** 2)), "ece10_model": rt.ece(y_te, s_model),
                  "bootstrap_model_minus_rule": rt.paired_bootstrap(y_te, raw_te, s_rule, days // 7,
                                                                   cfg["bootstrap_reps"], cfg["random_seed"])})
        k = cfg["budget_objects_per_day"]
        for name, sc in (("model", s_model), ("rule", s_rule)):
            b = rt.budget_curve(days, refs, y_te, sc, [k], cfg["cooldown_days"])[str(k)]
            m[f"top{k}_{name}"] = {x: b[x] for x in ("alerts_cooldown", "precision_cooldown", "recall_cooldown")}
    ci = (m.get("bootstrap_model_minus_rule") or {}).get("ci95_low")
    res["gate"] = "passed" if (ci is not None and ci > 0) else "baseline_only"
    res.update({"model": model, "platt": _lr_params(p_model), "rule_platt": _lr_params(p_rule),
                "importance": model.importance(8)})
    return res


def learning_curve(pl: Any, tr: Any, ca: Any, te: Any, kind: str, feats: list[str], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for n in cfg["learning_curve_sizes"]:
        r = fit_type(pl, tr, ca, te, kind, feats, cfg, n_pos=n, seed=cfg["random_seed"], full=False)
        if r.get("gate") in ("insufficient_labels", "skipped_size"):
            continue
        out.append({"n_train_positives": n, **{k: r["test_metrics"].get(k) for k in ("pr_auc_model", "lift_model", "prevalence")}})
    return out


def decision_status(gate: str, label_source: str) -> str:
    if gate == "insufficient_labels":
        return "insufficient_labels"
    if gate == "baseline_only":
        return "baseline_only"
    return "demo_stub" if label_source == "stub" else "experimental_shadow"


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------
def export_bundle(out_dir: Path, fits: dict[str, dict[str, Any]], feats: list[str], coverage: dict[str, Any],
                  register_sha: str, manifest: dict[str, Any], manifest_path: Path, cfg: dict[str, Any]) -> Path:
    bdir = Path(out_dir) / "incident_head_bundle"
    if bdir.exists():
        shutil.rmtree(bdir)
    bdir.mkdir(parents=True)
    label_source = coverage["label_source"]
    types, model_shas = {}, []
    for kind, f in fits.items():
        status = decision_status(f["gate"], label_source)
        t: dict[str, Any] = {"decision_status": status, "counts": f["counts"], "test_metrics": _public(f.get("test_metrics")),
                             "platt": f.get("platt"), "rule_platt": f.get("rule_platt"), "rule_features": ip.RULE_COLS[kind],
                             "model_file": None}
        if "model" in f and status in ("demo_stub", "experimental_shadow"):
            text = f["model"].model.booster_.model_to_string()
            (bdir / f"model_{kind}.txt").write_text(text, encoding="utf-8")
            t["model_file"] = f"model_{kind}.txt"
            model_shas.append(hashlib.sha256(text.encode("utf-8")).hexdigest())
        types[kind] = t
    tag = hashlib.sha256("".join(model_shas).encode()).hexdigest()[:12] if model_shas else "rules"
    spec = {
        "module": "incident_head", "agg_version": ip.AGG_VERSION,
        "model_version": f"incident-head-v1-{label_source}-{tag}",
        "feature_contract_version": f"event-panel-v{manifest.get('schema_version')}+{ip.AGG_VERSION}",
        "label_source": label_source, "evidence_level": "E0" if label_source == "register" else "E4",
        "operational_ready": False, "window": "[D+2; D+3)", "features": feats, "types": types,
        "coverage": coverage, "register_sha256": register_sha,
        "generator_version": (coverage.get("stub") or {}).get("generator_version"),
        "score_meaning": ("demo-score на искусственных метках, НЕ вероятность подтверждённого инцидента"
                          if label_source == "stub" else "вероятность начала подтверждённого инцидента в окне"),
        "split": {"train_end": cfg["train_end"], "cal_end": cfg["cal_end"], "test_end": cfg["test_end"]},
        "gates": {"min_train_positives": cfg["min_train_positives"], "min_calibration_positives": cfg["min_calibration_positives"],
                  "model_vs_rule": "нижняя граница 95 % CI блочного бутстрэпа ΔPR-AUC (модель − правило) > 0"},
        "panel": {"manifest_sha256": _sha256_file(manifest_path), "rows": manifest.get("rows"),
                  "schema_version": manifest.get("schema_version")},
        "backend_rules": ["при label_source = stub — плашка «ДЕМО: обучено на заглушке реестра»",
                          "score разных типов и газовый score не складываются",
                          "top-k объектов в сутки на тип и cooldown 72 ч применяет backend",
                          "автоматических заявок нет"],
        "versions": {m: __import__(m).__version__ for m in ("numpy", "polars", "lightgbm", "sklearn")},
    }
    (bdir / "bundle.json").write_text(_dump(spec), encoding="utf-8")
    shutil.copy(MODULE_DIR / "incident_predictor_v1.py", bdir / "predictor.py")
    (bdir / "README_RU.md").write_text(bundle_readme(spec), encoding="utf-8")
    sums = {p.name: _sha256_file(p) for p in sorted(bdir.iterdir()) if p.is_file()}
    (bdir / "SHA256SUMS.json").write_text(json.dumps(sums, indent=2), encoding="utf-8")
    z = Path(out_dir) / "incident_head_bundle.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        for p in sorted(bdir.iterdir()):
            f.write(p, f"incident_head_bundle/{p.name}")
    (Path(out_dir) / "incident_head_bundle.zip.sha256").write_text(f"{_sha256_file(z)}  incident_head_bundle.zip\n")
    return bdir


def _public(m: Any) -> Any:
    return None if m is None else {k: v for k, v in m.items()}


def bundle_readme(spec: dict[str, Any]) -> str:
    L = [f"# incident_head bundle — {spec['model_version']}", "",
         f"Источник меток: **{spec['label_source']}**, уровень доказательности {spec['evidence_level']}. "
         "Окно прогноза [D+2; D+3), признаки на конец D.", ""]
    if spec["label_source"] == "stub":
        L += ["**ДЕМО.** Модель обучена на заглушке реестра. Цифры показывают работу конвейера и порядок числа нужных меток, "
              "а не качество на реальных инцидентах.", ""]
    L += ["| тип | статус | 1 в train / калибровке / проверке |", "|---|---|---|"]
    for k, t in spec["types"].items():
        c = t["counts"]
        L.append(f"| {ip.TYPE_RU[k]} | {t['decision_status']} | {c.get('train_pos')} / {c.get('calibration_pos')} / {c.get('test_pos')} |")
    L += ["", "Вызов: `b = predictor.load_bundle(dir)`; `predictor.predict(channel_records, b, as_of_date)`.",
          "Контракт: docs/INCIDENT_REGISTER_CONTRACT_RU.md."]
    return "\n".join(L) + "\n"


def _import_predictor(bdir: Path) -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("incident_bundle_predictor", bdir / "predictor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def acceptance(pl: Any, bdir: Path, parts: list[Path], obj: Any, fits: dict[str, Any], feats: list[str],
               cfg: dict[str, Any]) -> dict[str, Any]:
    """Parity: predictor из bundle на канальных строках одних суток против модели в памяти на объектной панели."""
    pred = _import_predictor(bdir)
    b = pred.load_bundle(bdir)
    day = cfg["cal_end"] + timedelta(days=30)
    ch = pl.scan_parquet(parts).filter(pl.col("d_cutoff_date") == day).collect()
    if cfg["mode"] == "SMOKE":
        ch = ch.filter(pl.col("d_object_key").hash(seed=7) % cfg["smoke_object_share"] == 0)
    rep: dict[str, Any] = {"day": day, "objects": int(ch["d_object_key"].n_unique()) if ch.height else 0}
    if not ch.height:
        rep["parity_max_abs_diff"] = None
        return rep
    out = pred.predict(ch, b, day, request_id="acceptance", object_col="d_object_key")
    ref = obj.filter(pl.col("d_cutoff_date") == day)
    diffs, paths = [], {}
    for kind, f in fits.items():
        t = b["spec"]["types"][kind]
        if t["model_file"] is not None:
            mem = rt.apply_platt(_lr_obj(f["platt"]), f["model"].score(ref), True, 0.0)
            paths[kind] = "model"
        elif t["decision_status"] == "baseline_only":
            mem = rt.apply_platt(_lr_obj(f["rule_platt"]), ip.rule_raw(ref, kind), False, 0.0)
            paths[kind] = "rule"
        else:
            paths[kind] = "abstain"
            continue
        mp = dict(zip(ref["object_ref"].to_list(), mem))
        got = {r["d_object_key"]: r["score"] for r in out if r["incident_type"] == ip.TYPE_RU[kind]}
        diffs += [abs(got[o] - mp[o]) for o in mp if got.get(o) is not None]
    rep["parity_paths"] = paths
    rep["parity_max_abs_diff"] = float(max(diffs)) if diffs else None
    rep["records"] = len(out)
    rep["has_top_factors"] = any(r["top_factors"] for r in out)
    try:
        pred.predict(ch.head(3), b, "25.09.2026")
        rep["bad_date_rejected"] = False
    except pred.ContractError:
        rep["bad_date_rejected"] = True
    return rep


def _lr_obj(p: dict[str, float]) -> Any:
    class _M:
        def predict_proba(self, z: np.ndarray) -> np.ndarray:
            q = 1 / (1 + np.exp(-(p["coef"] * z[:, 0] + p["intercept"])))
            return np.c_[1 - q, q]
    return _M()


# ---------------------------------------------------------------------------
# Прогон
# ---------------------------------------------------------------------------
def run_scenario(pl: Any, obj: Any, feats: list[str], reg: Any, coverage: dict[str, Any], cfg: dict[str, Any],
                 log: Any, curves: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    ev, stats = load_register(pl, reg, coverage)
    frame = build_targets(pl, obj, ev, coverage)
    tr, ca, te = split(pl, frame, cfg)
    fits, report = {}, {"register": stats, "types": {},
                        "label_reasons": {k: {str(r): int(n) for r, n in frame[f"reason_{k}"].value_counts().iter_rows()}
                                          for k in ip.GROUPS}}
    for kind in ip.GROUPS:
        f = fit_type(pl, tr, ca, te, kind, feats, cfg)
        fits[kind] = f
        r = {"gate": f["gate"], "decision_status": decision_status(f["gate"], coverage["label_source"]),
             "counts": f["counts"], "test_metrics": f.get("test_metrics"), "importance": f.get("importance")}
        if curves and f["gate"] != "insufficient_labels":
            r["learning_curve"] = learning_curve(pl, tr, ca, te, kind, feats, cfg)
        report["types"][kind] = r
        m = f.get("test_metrics") or {}
        log(f"  {ip.TYPE_RU[kind]}: {r['decision_status']}; 1 в train/кал/тест {f['counts']['train_pos']}/"
            f"{f['counts']['calibration_pos']}/{f['counts']['test_pos']}; PR-AUC модель {m.get('pr_auc_model')} "
            f"правило {m.get('pr_auc_rule')} prevalence {m.get('prevalence')}")
    return fits, report


def run_incident_head(cfg: dict[str, Any], log: Any = print) -> dict[str, Any]:
    import polars as pl

    t0 = time.time()
    out_dir = Path(cfg["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    parts, manifest = rt.discover_panel(Path(cfg["input_dir"]), cfg["verify_sha256"])
    manifest_path = sorted(Path(cfg["input_dir"]).rglob("panel_manifest_v3.json"))[0]
    obj = build_object_panel(pl, parts, cfg)
    feats = ip.feature_columns(obj.columns)
    groups = (pl.scan_parquet(parts).select("d_channel_key", "тип_датчика").unique().with_columns(ip.group_expr(pl))
              .group_by("тип_датчика", "_grp").agg(pl.len().alias("channels")).sort("channels", descending=True).collect())
    type_groups = {str(t): {"group": g, "channels": int(n)} for t, g, n in groups.iter_rows()}
    log(f"объектная панель: {obj.height:,} строк объект×сутки, {obj['object_ref'].n_unique():,} объектов, признаков {len(feats)}")
    payload: dict[str, Any] = {"status": None, "mode": cfg["mode"], "features": len(feats), "object_days": obj.height,
                               "objects": int(obj["object_ref"].n_unique()), "type_groups": type_groups, "scenarios": {},
                               "protocol": {k: cfg[k] for k in ("rate_per_object_year", "no_trace_share", "stub_seed",
                                                                "min_train_positives", "min_calibration_positives",
                                                                "budget_objects_per_day", "cooldown_days",
                                                                "learning_curve_sizes", "train_end", "cal_end", "test_end")}}
    if cfg.get("register_path"):
        rp = Path(cfg["register_path"])
        reg = pl.read_parquet(rp) if rp.suffix == ".parquet" else pl.read_csv(rp, infer_schema_length=0).with_columns(
            pl.col("подтверждён").str.to_lowercase().is_in(["true", "1", "да"]))
        coverage = validate_coverage(json.loads(Path(cfg["coverage_path"]).read_text(encoding="utf-8")))
        log("реальный реестр")
        main_fits, rep = run_scenario(pl, obj, feats, reg, coverage, cfg, log, curves=True)
        payload["scenarios"]["register"] = rep
        main_reg, main_cov, reg_sha = reg, coverage, _sha256_file(rp)
    else:
        main_fits = None
        for name, beta in cfg["scenarios"].items():
            log(f"заглушка «{name}» (β = {beta})")
            reg, coverage = make_stub_register(pl, obj, cfg, beta, cfg["stub_seed"])
            fits, rep = run_scenario(pl, obj, feats, reg, coverage, cfg, log, curves=(name == cfg["main_scenario"]))
            rep["beta"] = beta
            payload["scenarios"][name] = rep
            if name == cfg["main_scenario"]:
                main_fits, main_reg, main_cov = fits, reg, coverage
        (out_dir / "incident_register_stub.csv").write_bytes(main_reg.write_csv().encode("utf-8"))
        (out_dir / "incident_register_coverage_stub.json").write_text(_dump(main_cov), encoding="utf-8")
        reg_sha = _sha256_file(out_dir / "incident_register_stub.csv")
    bdir = export_bundle(out_dir, main_fits, feats, main_cov, reg_sha, manifest, manifest_path, cfg)
    payload["bundle"] = {"zip_sha256": (out_dir / "incident_head_bundle.zip.sha256").read_text().split()[0],
                         "model_version": json.loads((bdir / "bundle.json").read_text(encoding="utf-8"))["model_version"]}
    payload["acceptance"] = acceptance(pl, bdir, parts, obj, main_fits, feats, cfg)
    payload["status"] = "completed_smoke_non_comparable" if cfg["mode"] == "SMOKE" else "completed"
    payload["runtime_s"] = round(time.time() - t0, 1)
    (out_dir / "results_18_incident_head.json").write_text(_dump(payload), encoding="utf-8")
    (out_dir / "summary_18_incident_head_ru.md").write_text(summary_markdown(payload, cfg), encoding="utf-8")
    return payload


def _f(x: Any, d: int = 3) -> str:
    return "—" if x is None else f"{x:.{d}f}"


def summary_markdown(p: dict[str, Any], cfg: dict[str, Any]) -> str:
    stub = "register" not in p["scenarios"]
    L = [f"# 18 · Модуль прогноза инцидентов по реестру — {p['status']}", ""]
    if stub:
        L += ["**ДЕМО на заглушке реестра** (evidence E4). Цифры показывают работу конвейера и порядок числа нужных меток, "
              "а не качество на реальных инцидентах. Сценарий `control` (β = 0) — проверка честности: модель не должна "
              "обгонять правило и случайный уровень.", ""]
    L += [f"Объектная панель: {p['object_days']:,} объект×сутки, {p['objects']:,} объектов, {p['features']} признаков. "
          f"Разбиение: train до {cfg['train_end']}, калибровка до {cfg['cal_end']}, проверка до {cfg['test_end']}. "
          "2025 H2 проектом уже просматривался — это development-проверка, не независимый тест.", ""]
    tg: dict[str, list[str]] = {}
    for t, v in p.get("type_groups", {}).items():
        tg.setdefault(v["group"], []).append(f"{t} ({v['channels']:,})")
    L += ["Группы типов датчиков (по названию, заданы до запуска): " + "; ".join(
        f"**{ip.GROUP_RU.get(g, g)}** — {', '.join(v[:8])}{' …' if len(v) > 8 else ''}" for g, v in tg.items()), ""]
    k = cfg["budget_objects_per_day"]
    for name, sc in p["scenarios"].items():
        L += [f"## {name}" + (f" (β = {sc['beta']})" if "beta" in sc else ""), "",
              f"Инцидентов в реестре (в рамках ТЗ): {sc['register']['confirmed_in_scope']:,} "
              f"({', '.join(f'{ip.TYPE_RU[t]} {n:,}' for t, n in sc['register']['by_type'].items())}). "
              "Исключено из меток как конкурирующее событие в D+1: "
              + ", ".join(f"{ip.TYPE_RU[t]} {r.get('competing_event_d1', 0):,}" for t, r in sc["label_reasons"].items()) + ".", "",
              f"| тип | статус | 1 train/кал/тест | prevalence | PR-AUC модель | PR-AUC правило | lift модель | Δ модель−правило [95 %] | top-{k}/сутки модель: precision / recall |",
              "|---|---|---|---|---|---|---|---|---|"]
        for kind, r in sc["types"].items():
            m, c = r.get("test_metrics") or {}, r["counts"]
            b = m.get("bootstrap_model_minus_rule") or {}
            ci = f"{_f(b.get('mean'))} [{_f(b.get('ci95_low'))}; {_f(b.get('ci95_high'))}]" if b.get("mean") is not None else "—"
            tk = m.get(f"top{k}_model") or {}
            L.append(f"| {ip.TYPE_RU[kind]} | {r['decision_status']} | {c['train_pos']}/{c['calibration_pos']}/{c['test_pos']} | "
                     f"{_f(m.get('prevalence'), 4)} | {_f(m.get('pr_auc_model'))} | {_f(m.get('pr_auc_rule'))} | "
                     f"{_f(m.get('lift_model'), 1)} | {ci} | {_f(tk.get('precision_cooldown'))} / {_f(tk.get('recall_cooldown'))} |")
        curves = {kind: r["learning_curve"] for kind, r in sc["types"].items() if r.get("learning_curve")}
        if curves:
            L += ["", "Кривая обучения (PR-AUC модели на проверке при N положительных в train):", "",
                  "| тип | " + " | ".join(f"N = {n}" for n in cfg["learning_curve_sizes"]) + " | все |",
                  "|---|" + "---|" * (len(cfg["learning_curve_sizes"]) + 1)]
            for kind, cur in curves.items():
                byn = {x["n_train_positives"]: x["pr_auc_model"] for x in cur}
                allv = (sc["types"][kind].get("test_metrics") or {}).get("pr_auc_model")
                L.append(f"| {ip.TYPE_RU[kind]} | " + " | ".join(_f(byn.get(n)) for n in cfg["learning_curve_sizes"])
                         + f" | {_f(allv)} |")
        L.append("")
    a = p["acceptance"]
    L += ["## Приёмка bundle", "",
          f"- `{p['bundle']['model_version']}`, ZIP sha256 `{p['bundle']['zip_sha256'][:12]}…`.",
          f"- Parity predictor из bundle ↔ расчёт в памяти на сутках {a.get('day')} (пути: {a.get('parity_paths')}): max |Δ| = {a.get('parity_max_abs_diff')}.",
          f"- top_factors есть: {a.get('has_top_factors')}; неверная дата отклоняется: {a.get('bad_date_rejected')}.", ""]
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Синтетическая канальная панель для тестов (не реальные данные)
# ---------------------------------------------------------------------------
SYNTH_TYPES = ["Газовый датчик", "Датчик дыма", "Датчик затопления", "Состояние насоса", "Датчик движения", "КД Дверь"]


def synthetic_incident_panel(out_dir: Path, n_objects: int = 60, seed: int = 5,
                             start: date = date(2022, 1, 1), end: date = date(2026, 1, 10)) -> Path:
    """Суточная панель v3-формы: у объекта 6 каналов; активность тревог — AR(1) по логарифму интенсивности,
    поэтому всплеск в D+2 частично предсказуем по истории. Для тестов модуля 18."""
    import polars as pl

    rng = np.random.default_rng(seed)
    days = np.arange(np.datetime64(start), np.datetime64(end))
    n_days, n_ch = len(days), n_objects * len(SYNTH_TYPES)
    lam = np.zeros(n_ch)
    alarms = np.zeros((n_days, n_ch))
    season = 1 + 0.8 * np.sin(2 * np.pi * (days.astype("datetime64[D]").astype(int) % 365) / 365)
    is_flood = np.tile(np.isin(SYNTH_TYPES, ["Датчик затопления", "Состояние насоса"]), n_objects)
    for t in range(n_days):
        lam = 0.92 * lam + rng.normal(0, 0.35, n_ch)
        rate = 0.3 * np.exp(lam) * np.where(is_flood, season[t], 1.0)
        alarms[t] = rng.poisson(rate)
    csum = np.vstack([np.zeros((1, n_ch)), np.cumsum(alarms, axis=0)])
    idx = np.arange(n_days)
    a7 = csum[idx + 1] - csum[np.maximum(idx - 6, 0)]
    a30 = csum[idx + 1] - csum[np.maximum(idx - 29, 0)]
    ch = np.tile(np.arange(n_ch), n_days)
    obj = ch // len(SYNTH_TYPES)
    typ = np.array(SYNTH_TYPES)[ch % len(SYNTH_TYPES)]
    n = n_days * n_ch
    gas = np.where(typ == "Газовый датчик", rng.uniform(0, 0.8, n) + (alarms.ravel() > 2) * 0.6, np.nan)
    frame = {
        "d_channel_key": np.array([hashlib.sha256(f"c{c}".encode()).hexdigest()[:16] for c in range(n_ch)])[ch],
        "d_object_key": np.array([hashlib.sha256(f"o{o}".encode()).hexdigest()[:16] for o in range(n_objects)])[obj],
        "d_cutoff_date": np.repeat(days, n_ch), "тип_датчика": typ,
        "link_state": rng.choice(["O", "F", "A"], n, p=[0.93, 0.04, 0.03]),
        "power_state": rng.choice(["O", "F"], n, p=[0.95, 0.05]),
        "n_alarm": alarms.ravel(), "n_events": alarms.ravel() + rng.poisson(20, n),
        "f_n_alarm_7d": a7.ravel(), "f_n_alarm_30d": a30.ravel(), "f_n_events_7d": a7.ravel() + rng.poisson(140, n),
        "f_n_flood_7d": np.where(is_flood[ch], a7.ravel(), 0.0), "f_n_link_fault_7d": rng.poisson(0.2, n).astype(float),
        "gas_max": gas, "f_gas_ge_thr_n_7d": np.where(np.nan_to_num(gas) >= 1, 1.0, 0.0),
    }
    panel = pl.DataFrame(frame).with_columns(pl.col("d_cutoff_date").cast(pl.Date))
    panel_dir = Path(out_dir) / "event_panel_v3"
    panel_dir.mkdir(parents=True, exist_ok=True)
    part = panel_dir / "event_panel_v3_part00.parquet"
    panel.write_parquet(part)
    manifest = {"schema_version": rt.SCHEMA_VERSION, "rows": panel.height, "taxonomy_sha256": "synthetic",
                "panel_config": {"synthetic": True, "module": "18"}, "feature_columns": [c for c in panel.columns if c.startswith("f_")],
                "target_columns": [], "parts": [{"file": part.name, "sha256": rt.file_sha256(part), "rows": panel.height}]}
    (panel_dir / "panel_manifest_v3.json").write_text(json.dumps(manifest), encoding="utf-8")
    return panel_dir


# ---------------------------------------------------------------------------
# CLI (дообучение на реальном реестре)
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="incident_head: обучение по реестру инцидентов")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--panel", required=True, help="каталог с выходом ноутбука 14 (panel_manifest_v3.json)")
    t.add_argument("--register", help="incident_register.csv|.parquet; без него — заглушка")
    t.add_argument("--coverage", help="incident_register_coverage.json")
    t.add_argument("--out", required=True)
    t.add_argument("--mode", default="FULL", choices=["FULL", "SMOKE"])
    a = ap.parse_args(argv)
    if bool(a.register) != bool(a.coverage):
        ap.error("реестр и покрытие передаются вместе")
    cfg = make_config_18(a.mode, {"input_dir": a.panel, "output_dir": a.out, "register_path": a.register,
                                  "coverage_path": a.coverage})
    res = run_incident_head(cfg)
    print(json.dumps({k: res["scenarios"][s]["types"][k]["decision_status"] for s in res["scenarios"]
                      for k in res["scenarios"][s]["types"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
