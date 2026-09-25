"""Ноутбук 15: сравнение моделей на целях панели v3 (T2a/T2b/T2c/T1a/T4) и typed-score контракт для бэкенда.

Протокол зафиксирован до обучения (docs/EXPERIMENT_15_TARGETS_V3_RU.md):
- только pre-2025, фолды fold_2023 / fold_2024 как в ноутбуке 05; 2021 (переход системы мониторинга, FAQ)
  и 30 суток прогрева после него исключены;
- purging по d_label_decision_end: метка обучающей строки решена до начала калибровки, калибровочной — до валидации;
- модели: P0 априорная частота по типу датчика, R1 правило (недавние эпизоды), L1 логистическая регрессия,
  G1 LightGBM, G2 LightGBM без календаря, G3 LightGBM без типа датчика/системы (проверка shortcut);
- метрики: PR-AUC, ROC-AUC, Brier/ECE после Platt (калибровка на H1), бюджетная кривая top-k в сутки
  с cooldown 72 ч и без; парный блочный бутстрэп по неделям для G1 против лучшего простого baseline;
- выбор и evidence_level по заранее заданным gates; результат — typed-score контракт без построчных прогнозов.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA_VERSION = "3.0"
TARGET_SPECS: dict[str, dict[str, Any]] = {
    "target_t2a_link_onset": {"tz": "T2a", "incident_type": "link_loss_onset", "family": "probability",
                              "rule": ("f_link_onset_strict_30d", "f_link_onset_strict_7d"), "competing": "competing_link_onset_d1"},
    "target_t2b_link_sustained": {"tz": "T2b", "incident_type": "link_loss_sustained",
                                  "family": "conditional_proxy_score",
                                  "rule": ("f_link_completed_long_30d", "f_link_onset_strict_7d"), "competing": "competing_link_onset_d1"},
    "target_t2c_power_onset": {"tz": "T2c", "incident_type": "power_loss_onset", "family": "probability",
                               "rule": ("f_power_onset_strict_30d", "f_power_onset_strict_7d"), "competing": "competing_power_onset_d1"},
    "target_t2c_power_sustained": {"tz": "T2c", "incident_type": "power_loss_sustained",
                                   "family": "conditional_proxy_score",
                                   "rule": ("f_power_completed_long_30d", "f_power_onset_strict_7d"), "competing": "competing_power_onset_d1"},
    "target_t1a_tech_value": {"tz": "T1a", "incident_type": "measurement_fault_onset",
                              "family": "probability",
                              "rule": ("f_n_tech_like_30d", "f_n_undefined_measurement_30d"), "competing": None},
    "target_t4_gas_cross": {"tz": "T4", "incident_type": "gas_threshold_cross", "family": "probability",
                            "rule": ("f_gas_max_7d", "f_gas_band_n_7d"), "competing": "competing_gas_cross_d1"},
}
CATEGORICAL = ["link_state", "power_state", "тип_датчика", "тип_инж_системы"]
CALENDAR = ["d_weekday", "d_month"]
CATALOGUE = ["тип_датчика", "тип_инж_системы"]
FORBIDDEN_PREFIXES = ("target_", "reason_", "competing_", "d_label", "d_target", "d_channel", "d_object", "d_cutoff")
FOLDS = [
    {"name": "fold_2023", "train_end": date(2023, 1, 1), "calibration": (date(2023, 1, 1), date(2023, 7, 1)),
     "validation": (date(2023, 7, 1), date(2024, 1, 1))},
    {"name": "fold_2024", "train_end": date(2024, 1, 1), "calibration": (date(2024, 1, 1), date(2024, 7, 1)),
     "validation": (date(2024, 7, 1), date(2025, 1, 1))},
]
LOAD_END = date(2025, 1, 1)
EXCLUDED = (date(2021, 1, 1), date(2022, 1, 31))   # 2021 + 30 суток прогрева окон признаков
# selectable, но исход неизвестен: такие строки ранжируются в бюджете (слоты в unknown считаются), но не входят в PR-AUC
UNKNOWN_REASONS = ["unobserved_window", "ambiguous_onset", "censored_duration", "unknown_previous_reading"]
MODELS = ["P0_type_prior", "R1_rule", "L1_logistic", "G1_lightgbm", "G2_no_calendar", "G3_no_catalogue"]
BASELINES_FOR_GATE = ["P0_type_prior", "R1_rule"]


def make_config_targets(mode: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    if mode not in ("FULL", "SMOKE"):
        raise ValueError("MODE должен быть FULL или SMOKE")
    smoke = mode == "SMOKE"
    cfg = {
        "mode": mode,
        "input_dir": os.environ.get("LDT_KAGGLE_INPUT_DIR", "/kaggle/input"),
        "output_dir": os.environ.get("LDT_OUTPUT_DIR", "/kaggle/working"),
        "targets": list(TARGET_SPECS),
        "smoke_channel_share": 10,
        "verify_sha256": True,
        "random_seed": 42,
        "lgbm_iterations": 60 if smoke else 300,
        "max_neg_per_pos": 30,
        "max_train_rows": 300_000 if smoke else 2_000_000,
        "max_logistic_rows": 100_000 if smoke else 500_000,
        "budgets_per_day": [5, 10, 25, 50],
        "cooldown_days": 3,
        "bootstrap_reps": 20 if smoke else 100,
        "min_val_positives": 30,
        "shortcut_tolerance": 0.10,
        "ece_calibrated_max": 0.02,      # probability_calibrated только при ECE ≤ 0,02 в обоих фолдах
        "min_known_share_selectable": 0.5,  # g6: в валидации исход известен хотя бы у половины selectable строк
        "max_unknown_share_calibrated": 0.10,  # probability_calibrated: unknown среди selectable ≤ 10 %
        "min_type_positives": 30,        # срез по типам датчиков: типы с ≥ 30 положительными
    }
    cfg.update(overrides or {})
    return cfg


# ---------------------------------------------------------------------------
# Данные
# ---------------------------------------------------------------------------
def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(1 << 22):
            h.update(block)
    return h.hexdigest()


def discover_panel(input_dir: Path, verify: bool) -> tuple[list[Path], dict[str, Any]]:
    found = sorted(Path(input_dir).rglob("panel_manifest_v3.json"))
    if not found:
        raise FileNotFoundError("panel_manifest_v3.json не найден: подключите выход ноутбука 14 как Input")
    manifest_path = found[0]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"ожидалась схема {SCHEMA_VERSION}, в manifest {manifest.get('schema_version')}")
    parts = []
    for part in manifest["parts"]:
        p = manifest_path.parent / part["file"]
        if verify and file_sha256(p) != part["sha256"]:
            raise ValueError(f"SHA-256 части {part['file']} не совпадает с manifest")
        parts.append(p)
    import polars as pl

    rows = sum(int(pl.scan_parquet(p).select(pl.len()).collect().item()) for p in parts)
    if rows != manifest["rows"]:
        raise ValueError(f"строк в частях {rows:,}, в manifest {manifest['rows']:,}")
    return parts, manifest


def safe_features(manifest: dict[str, Any], columns: list[str]) -> list[str]:
    # тип датчика/системы — справочные метаданные канала (есть в панели, но не в списке признаков manifest v3)
    feats = [c for c in dict.fromkeys(list(manifest["feature_columns"]) + CATALOGUE) if c in columns]
    bad = [c for c in feats if c.startswith(FORBIDDEN_PREFIXES)]
    if bad:
        raise ValueError(f"запрещённые признаки: {bad}")
    return feats


def load_target(pl: Any, parts: list[Path], target: str, features: list[str], cfg: dict[str, Any],
                load_end: date = LOAD_END) -> Any:
    """load_end: граница загрузки (15 — всегда 2025-01-01; финальный экспорт 16 задаёт свою по рецепту)."""
    reason = "reason_" + target[len("target_"):]
    lf = pl.scan_parquet(parts)
    lf = lf.filter((pl.col("d_cutoff_date") < load_end) & (pl.col("d_label_decision_end") <= load_end)
                   & ~pl.col("d_cutoff_date").is_between(EXCLUDED[0], EXCLUDED[1], closed="left"))
    if cfg["mode"] == "SMOKE":
        lf = lf.filter(pl.col("d_channel_key").hash(seed=7) % cfg["smoke_channel_share"] == 0)
    numeric = [c for c in features if c not in CATEGORICAL]
    comp = TARGET_SPECS[target].get("competing")
    extra = [comp] if comp and comp in lf.collect_schema().names() else []
    cols = ["d_channel_key", "d_cutoff_date", "d_label_decision_end", target, reason] + extra + features
    return (lf.filter(pl.col(target).is_not_null() | pl.col(reason).is_in(UNKNOWN_REASONS)).select(cols)
            .with_columns([pl.col(c).cast(pl.Float32) for c in numeric]).collect())


STRESS_PERIOD = (date(2021, 1, 1), date(2022, 1, 1))   # переход системы мониторинга (FAQ): только stress-срез


def load_stress(pl: Any, parts: list[Path], target: str, features: list[str], cfg: dict[str, Any]) -> Any:
    """2021 — не участвует ни в обучении, ни в выборе; оценивается один раз моделями fold_2024 (GPT 20)."""
    lf = pl.scan_parquet(parts).filter(pl.col("d_cutoff_date").is_between(*STRESS_PERIOD, closed="left")
                                       & (pl.col("d_label_decision_end") <= STRESS_PERIOD[1]) & pl.col(target).is_not_null())
    if cfg["mode"] == "SMOKE":
        lf = lf.filter(pl.col("d_channel_key").hash(seed=7) % cfg["smoke_channel_share"] == 0)
    numeric = [c for c in features if c not in CATEGORICAL]
    return lf.select([target] + features).with_columns([pl.col(c).cast(pl.Float32) for c in numeric]).collect()


def coverage(pl: Any, parts: list[Path], targets: list[str], cfg: dict[str, Any]) -> dict[str, Any]:
    lf = pl.scan_parquet(parts).filter((pl.col("d_cutoff_date") < LOAD_END)
                                       & ~pl.col("d_cutoff_date").is_between(EXCLUDED[0], EXCLUDED[1], closed="left"))
    if cfg["mode"] == "SMOKE":
        lf = lf.filter(pl.col("d_channel_key").hash(seed=7) % cfg["smoke_channel_share"] == 0)
    total = int(lf.select(pl.len()).collect().item())
    out: dict[str, Any] = {"rows_pre2025_without_2021": total, "targets": {}}
    for t in targets:
        r = "reason_" + t[len("target_"):]
        g = lf.group_by(r).agg(pl.len()).collect()
        reasons = {str(k): int(v) for k, v in g.iter_rows()}
        labelled = reasons.get("positive", 0) + reasons.get("negative", 0) + reasons.get("negative_transient_only", 0)
        by_type = (lf.group_by("тип_датчика").agg(pl.col(t).is_not_null().mean().alias("share"), pl.len().alias("rows"))
                   .filter(pl.col("rows") >= 1000).sort("rows", descending=True).head(15).collect())
        out["targets"][t] = {"labelled_rows": labelled, "labelled_share": labelled / max(total, 1),
                             "reasons": reasons,
                             "labelled_share_by_sensor_type": {str(k or "нет в справочнике"): round(float(s), 4)
                                                                for k, s, _ in by_type.iter_rows()}}
    return out


def split_fold(pl: Any, frame: Any, fold: dict[str, Any]) -> tuple[Any, Any, Any]:
    c0, c1 = fold["calibration"]
    v0, v1 = fold["validation"]
    d, e = pl.col("d_cutoff_date"), pl.col("d_label_decision_end")
    train = frame.filter((d < fold["train_end"]) & (e <= c0))
    cal = frame.filter((d >= c0) & (d < c1) & (e <= v0))
    val = frame.filter((d >= v0) & (d < v1) & (e <= v1))
    return train, cal, val


def sample_train(pl: Any, train: Any, target: str, cfg: dict[str, Any]) -> Any:
    pos = train.filter(pl.col(target) == 1)
    neg = train.filter(pl.col(target) == 0)
    n_neg = min(neg.height, max(pos.height * cfg["max_neg_per_pos"], 1), max(cfg["max_train_rows"] - pos.height, 1))
    rate = n_neg / max(neg.height, 1)
    neg = neg.sample(n=n_neg, seed=cfg["random_seed"]) if n_neg < neg.height else neg
    return pl.concat([pos.with_columns(pl.lit(1.0).alias("_w")),
                      neg.with_columns(pl.lit(1.0 / max(rate, 1e-9)).alias("_w"))])


# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------
def _pandas(frame: Any, cols: list[str], levels: dict[str, list[str]]) -> Any:
    import pandas as pd

    x = pd.DataFrame({c: frame[c].to_numpy() for c in cols})
    for c in cols:
        if c in CATEGORICAL:
            v = frame[c].fill_null("__NA__").cast(str).to_numpy()
            x[c] = pd.Categorical(v, categories=levels[c])
    return x


class TypePrior:
    def fit(self, train: Any, target: str, m: float = 50.0) -> "TypePrior":
        import polars as pl

        w = train["_w"]
        y = train[target].cast(float)
        self.global_rate = float((w * y).sum() / w.sum())
        g = train.with_columns(y.alias("_y")).group_by("тип_датчика").agg(
            (pl.col("_w") * pl.col("_y")).sum().alias("p"), pl.col("_w").sum().alias("n"))
        self.rates = {k: (p + m * self.global_rate) / (n + m) for k, p, n in g.iter_rows()}
        return self

    def score(self, frame: Any) -> np.ndarray:
        return np.array([self.rates.get(k, self.global_rate) for k in frame["тип_датчика"].to_list()], dtype=float)


def rule_score(frame: Any, spec: dict[str, Any]) -> np.ndarray:
    a, b = spec["rule"]
    s = np.zeros(frame.height)
    for col, w in ((a, 1.0), (b, 0.5)):
        if col in frame.columns:
            s = s + w * np.nan_to_num(frame[col].to_numpy().astype(float))
    return s


class Logistic:
    def fit(self, train: Any, target: str, features: list[str], cfg: dict[str, Any]) -> "Logistic":
        from sklearn.linear_model import LogisticRegression

        if train.height > cfg["max_logistic_rows"]:
            train = train.sample(n=cfg["max_logistic_rows"], seed=cfg["random_seed"])
        self.num = [c for c in features if c not in CATEGORICAL]
        self.cat = {c: [str(v) for v in train[c].fill_null("__NA__").cast(str).value_counts(sort=True)[c].head(50).to_list()]
                    for c in features if c in CATEGORICAL}
        x = self._x(train, fit=True)
        self.model = LogisticRegression(C=1.0, max_iter=300, random_state=cfg["random_seed"])
        self.model.fit(x, train[target].to_numpy(), sample_weight=train["_w"].to_numpy())
        return self

    def _x(self, frame: Any, fit: bool = False) -> np.ndarray:
        num = np.column_stack([frame[c].to_numpy().astype(float) for c in self.num]) if self.num else np.zeros((frame.height, 0))
        num = np.nan_to_num(num, nan=0.0, posinf=0.0, neginf=0.0)
        num = np.sign(num) * np.log1p(np.abs(num))
        if fit:
            self.mu, self.sd = num.mean(0), num.std(0) + 1e-9
        num = (num - self.mu) / self.sd
        cats = [(frame[c].fill_null("__NA__").cast(str).to_numpy()[:, None] == np.array(lv)[None, :]).astype(float)
                for c, lv in self.cat.items()]
        return np.hstack([num] + cats)

    def score(self, frame: Any) -> np.ndarray:
        return self.model.predict_proba(self._x(frame))[:, 1]


class LightGBM:
    def fit(self, train: Any, target: str, features: list[str], cfg: dict[str, Any]) -> "LightGBM":
        from lightgbm import LGBMClassifier

        self.features = features
        self.levels = {c: sorted(str(v) for v in train[c].fill_null("__NA__").cast(str).unique().to_list())
                       for c in features if c in CATEGORICAL}
        self.model = LGBMClassifier(objective="binary", n_estimators=int(cfg["lgbm_iterations"]), learning_rate=0.05,
                                    num_leaves=63, max_bin=63, min_child_samples=100, subsample=0.8, subsample_freq=1,
                                    colsample_bytree=0.8, random_state=cfg["random_seed"], n_jobs=-1, verbosity=-1)
        cats = [c for c in features if c in CATEGORICAL]
        self.model.fit(_pandas(train, features, self.levels), train[target].to_numpy(),
                       sample_weight=train["_w"].to_numpy(), categorical_feature=cats or "auto")
        return self

    def score(self, frame: Any) -> np.ndarray:
        return self.model.predict_proba(_pandas(frame, self.features, self.levels))[:, 1]

    def importance(self, top: int = 12) -> dict[str, float]:
        gain = self.model.booster_.feature_importance("gain")
        total = float(gain.sum()) or 1.0
        order = np.argsort(-gain)[:top]
        return {self.features[i]: round(float(gain[i] / total), 4) for i in order}


# ---------------------------------------------------------------------------
# Метрики
# ---------------------------------------------------------------------------
def _z(score: np.ndarray, is_probability: bool) -> np.ndarray:
    if is_probability:
        p = np.clip(score, 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p))
    return np.log1p(np.maximum(score, 0))


def platt(raw_cal: np.ndarray, y_cal: np.ndarray, is_probability: bool) -> Any:
    from sklearn.linear_model import LogisticRegression

    if np.unique(y_cal).size < 2:
        return None
    m = LogisticRegression(max_iter=300)
    m.fit(_z(raw_cal, is_probability).reshape(-1, 1), y_cal)
    return m


def apply_platt(m: Any, raw: np.ndarray, is_probability: bool, prior: float) -> np.ndarray:
    if m is None:
        return np.full(len(raw), prior)
    return m.predict_proba(_z(raw, is_probability).reshape(-1, 1))[:, 1]


def ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    q = np.quantile(p, np.linspace(0, 1, bins + 1))
    idx = np.clip(np.searchsorted(q, p, side="right") - 1, 0, bins - 1)
    return float(sum((idx == b).mean() * abs(y[idx == b].mean() - p[idx == b].mean()) for b in range(bins) if (idx == b).any()))


def budget_curve(days: np.ndarray, channels: np.ndarray, y: np.ndarray, score: np.ndarray,
                 budgets: list[int], cooldown_days: int) -> dict[str, Any]:
    """top-k строк в сутки по всей selectable когорте; y: 1/0, −1 = исход неизвестен.
    precision — нижняя граница (unknown = 0), precision_upper — верхняя (unknown = 1); recall — по известным положительным.
    С cooldown канал не выдаётся повторно cooldown_days суток после алерта."""
    order = np.lexsort((-score, days))
    d_sorted, c_sorted, y_sorted = days[order], channels[order], y[order]
    starts = np.flatnonzero(np.r_[True, d_sorted[1:] != d_sorted[:-1]])
    ends = np.r_[starts[1:], len(order)]
    total_pos = int((y == 1).sum())
    total_unk = int((y == -1).sum())
    pos_sorted, unk_sorted = (y_sorted == 1).astype(int), (y_sorted == -1).astype(int)
    out = {}
    for k in budgets:
        tp = n = unk = 0
        tp_cd = n_cd = unk_cd = 0
        last: dict[Any, int] = {}
        for s, e in zip(starts, ends):
            tp += int(pos_sorted[s:min(e, s + k)].sum())
            unk += int(unk_sorted[s:min(e, s + k)].sum())
            n += min(e - s, k)
            day = int(d_sorted[s])
            taken = 0
            for i in range(s, e):
                if taken >= k:
                    break
                ch = c_sorted[i]
                if ch in last and day - last[ch] < cooldown_days:
                    continue
                last[ch] = day
                taken += 1
                tp_cd += int(pos_sorted[i])
                unk_cd += int(unk_sorted[i])
            n_cd += taken
        out[str(k)] = {"precision": tp / max(n, 1), "precision_upper": (tp + unk) / max(n, 1), "unknown_alerts": unk,
                       "recall": tp / max(total_pos, 1), "alerts": n,
                       # recall по GPT 16: нижняя — все неизвестные вне бюджета положительные, верхняя — все выданные unknown положительные
                       "recall_low": tp / max(total_pos + total_unk - unk, 1), "recall_up": (tp + unk) / max(total_pos + unk, 1),
                       "precision_cooldown": tp_cd / max(n_cd, 1), "precision_upper_cooldown": (tp_cd + unk_cd) / max(n_cd, 1),
                       "unknown_alerts_cooldown": unk_cd, "recall_cooldown": tp_cd / max(total_pos, 1),
                       "recall_low_cooldown": tp_cd / max(total_pos + total_unk - unk_cd, 1),
                       "recall_up_cooldown": (tp_cd + unk_cd) / max(total_pos + unk_cd, 1),
                       "alerts_cooldown": n_cd}
    return out


def evaluate(y: np.ndarray, raw: np.ndarray, cal: np.ndarray, budget_frame: tuple[np.ndarray, ...],
             cfg: dict[str, Any]) -> dict[str, Any]:
    """Ранжирующие метрики и калибровка — по строкам с известным исходом; бюджет — по всей selectable когорте."""
    days, channels, y_all, raw_all = budget_frame
    from sklearn.metrics import average_precision_score, roc_auc_score

    ok = np.unique(y).size == 2
    return {
        "pr_auc": float(average_precision_score(y, raw)) if ok else None,
        "roc_auc": float(roc_auc_score(y, raw)) if ok else None,
        "brier": float(np.mean((cal - y) ** 2)),
        "ece10": ece(y, cal),
        "budget": budget_curve(days, channels, y_all, raw_all, cfg["budgets_per_day"], cfg["cooldown_days"]),
    }


def by_type_pr_auc(y: np.ndarray, raw: np.ndarray, types: np.ndarray, min_pos: int) -> dict[str, float]:
    from sklearn.metrics import average_precision_score

    out = {}
    for t in np.unique(types):
        m = types == t
        if y[m].sum() >= min_pos and y[m].min() != y[m].max():
            out[str(t)] = float(average_precision_score(y[m], raw[m]))
    return out


def paired_bootstrap(y: np.ndarray, a: np.ndarray, b: np.ndarray, weeks: np.ndarray, reps: int, seed: int) -> dict[str, Any]:
    """PR-AUC(a) − PR-AUC(b), блоки = календарные недели, одни и те же выборки для обеих моделей."""
    from sklearn.metrics import average_precision_score

    uniq, inv = np.unique(weeks, return_inverse=True)
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(reps):
        w = np.bincount(rng.integers(0, len(uniq), len(uniq)), minlength=len(uniq))[inv].astype(float)
        m = w > 0
        if y[m].min() == y[m].max():
            continue
        diffs.append(average_precision_score(y[m], a[m], sample_weight=w[m])
                     - average_precision_score(y[m], b[m], sample_weight=w[m]))
    d = np.array(diffs)
    if not len(d):
        return {"mean": None, "ci95_low": None, "ci95_high": None, "reps": 0}
    return {"mean": float(d.mean()), "ci95_low": float(np.percentile(d, 2.5)),
            "ci95_high": float(np.percentile(d, 97.5)), "reps": int(len(d))}


# ---------------------------------------------------------------------------
# Прогон
# ---------------------------------------------------------------------------
def run_target(pl: Any, frame: Any, target: str, features: list[str], cfg: dict[str, Any], log: Any,
               stress: Any = None) -> dict[str, Any]:
    spec = TARGET_SPECS[target]
    res: dict[str, Any] = {"folds": {}}
    for fold in FOLDS:
        train, cal, val_all = split_fold(pl, frame, fold)
        known = pl.col(target).is_not_null()
        train, cal, val = train.filter(known), cal.filter(known), val_all.filter(known)
        n = {"train": train.height, "calibration": cal.height, "validation": val.height,
             "train_pos": int(train[target].sum()), "calibration_pos": int(cal[target].sum()),
             "validation_pos": int(val[target].sum()), "validation_selectable": val_all.height,
             "validation_unknown": val_all.height - val.height}
        fr: dict[str, Any] = {"rows": n, "models": {}}
        res["folds"][fold["name"]] = fr
        if min(n["train_pos"], n["calibration_pos"]) < 5 or n["validation_pos"] < 1:
            fr["skipped"] = "слишком мало положительных для обучения/калибровки"
            continue
        tr = sample_train(pl, train, target, cfg)
        y_cal, y_val = cal[target].to_numpy().astype(int), val[target].to_numpy().astype(int)
        days = np.array([(d - date(2019, 1, 1)).days for d in val["d_cutoff_date"].to_list()])
        weeks = days // 7
        days_all = np.array([(d - date(2019, 1, 1)).days for d in val_all["d_cutoff_date"].to_list()])
        chans_all = val_all["d_channel_key"].to_numpy()
        y_all = val_all[target].fill_null(-1).to_numpy().astype(int)
        known_mask = y_all >= 0
        prior = float(train[target].mean())
        raws: dict[str, np.ndarray] = {}
        fitted: dict[str, Any] = {}
        no_cal = [c for c in features if c not in CALENDAR]
        no_cat = [c for c in features if c not in CATALOGUE]
        for name in MODELS:
            t0 = time.time()
            if name == "P0_type_prior":
                m = TypePrior().fit(tr, target)
                is_p = True
            elif name == "R1_rule":
                m, is_p = None, False
            elif name == "L1_logistic":
                m, is_p = Logistic().fit(tr, target, features, cfg), True
            else:
                feats = {"G1_lightgbm": features, "G2_no_calendar": no_cal, "G3_no_catalogue": no_cat}[name]
                m, is_p = LightGBM().fit(tr, target, feats, cfg), True
            score = (lambda f: rule_score(f, spec)) if m is None else m.score
            raw_cal, raw_all = score(cal), score(val_all)
            raw_val = raw_all[known_mask]
            cal_model = platt(raw_cal, y_cal, is_p)
            p_val = apply_platt(cal_model, raw_val, is_p, prior)
            raws[name] = raw_val
            fitted[name] = m
            fr["models"][name] = evaluate(y_val, raw_val, p_val, (days_all, chans_all, y_all, raw_all), cfg)
            fr["models"][name]["fit_s"] = round(time.time() - t0, 1)
        fr["prevalence_validation"] = float(y_val.mean())
        fr["unknown_share_selectable"] = n["validation_unknown"] / max(n["validation_selectable"], 1)
        comp = spec.get("competing")
        if comp and comp in val.columns:
            from sklearn.metrics import average_precision_score
            # C5 / GPT 16: estimand «любой onset в D+2» против «первого» (onset в D+1 — отдельный исход), строки не удаляются
            c = val[comp].fill_null(False).to_numpy().astype(bool)
            y_first = (y_val == 1) & ~c
            fr["competing_d1"] = {"share_of_rows": float(c.mean()), "share_of_positives": float(c[y_val == 1].mean()) if y_val.sum() else None,
                                  "pr_auc_first_onset": {k: (float(average_precision_score(y_first, raws[k]))
                                                             if y_first.any() else None) for k in MODELS}}
        types = val["тип_датчика"].fill_null("нет в справочнике").to_numpy()
        fr["by_sensor_type_pr_auc"] = {k: by_type_pr_auc(y_val, raws[k], types, cfg["min_type_positives"]) for k in MODELS}
        fr["importance_G1"] = fitted["G1_lightgbm"].importance()
        best_base = max(BASELINES_FOR_GATE, key=lambda k: fr["models"][k]["pr_auc"] or -1)
        fr["best_simple_baseline"] = best_base
        for cand in ("G1_lightgbm", "G2_no_calendar", "L1_logistic"):
            fr[f"bootstrap_{cand}_vs_{best_base}"] = paired_bootstrap(
                y_val, raws[cand], raws[best_base], weeks, cfg["bootstrap_reps"], cfg["random_seed"])
        log(f"  {fold['name']}: val {n['validation']:,} строк, 1: {n['validation_pos']:,}; PR-AUC "
            + ", ".join(f"{k.split('_')[0]} {fr['models'][k]['pr_auc']:.3f}" for k in MODELS if fr['models'][k]['pr_auc'] is not None))
    res["decision"] = decide(res, cfg)
    last = res["folds"].get(FOLDS[-1]["name"], {})
    if stress is not None and stress.height and "skipped" not in last and last.get("models"):
        from sklearn.metrics import average_precision_score
        y_s = stress[target].to_numpy().astype(int)
        out = {"rows": stress.height, "positives": int(y_s.sum()), "prevalence": float(y_s.mean()), "pr_auc": {}}
        if 0 < y_s.sum() < len(y_s):
            for name, m in fitted.items():
                raw = rule_score(stress, spec) if m is None else m.score(stress)
                out["pr_auc"][name] = float(average_precision_score(y_s, raw))
        res["stress_2021"] = out
    return res


def decide(res: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    folds = list(res["folds"].values())
    gates: dict[str, Any] = {}
    gates["g1_enough_validation_events"] = all(f["rows"]["validation_pos"] >= cfg["min_val_positives"] and "skipped" not in f
                                               for f in folds)
    if not gates["g1_enough_validation_events"]:
        return {"gates": gates, "selected": None, "evidence_level": "insufficient_events",
                "abstain_reason": "too_few_validation_events"}

    def beats(model: str) -> bool:
        return all((f[f"bootstrap_{model}_vs_{f['best_simple_baseline']}"]["ci95_low"] or -1) > 0 for f in folds)

    def ratio(model: str) -> float:
        return min(f["models"][model]["pr_auc"] / max(f["models"]["G1_lightgbm"]["pr_auc"], 1e-12) for f in folds)

    tol = 1 - cfg["shortcut_tolerance"]
    gates["g2_G1_beats_simple_baselines_both_folds"] = beats("G1_lightgbm")
    gates["g3_no_calendar_shortcut"] = ratio("G2_no_calendar") >= tol
    gates["g4_no_catalogue_shortcut"] = ratio("G3_no_catalogue") >= tol
    base_means = {k: float(np.mean([f["models"][k]["pr_auc"] for f in folds])) for k in BASELINES_FOR_GATE}

    def stable(model: str) -> bool | None:
        """≥ 2/3 типов датчиков с поддержкой: модель лучше лучшего простого baseline в каждом фолде.
        Неприменимо (None), если в фолдах меньше двух типов с поддержкой (например, газовая цель T4)."""
        applicable = False
        for f in folds:
            base = f["by_sensor_type_pr_auc"][f["best_simple_baseline"]]
            mine = f["by_sensor_type_pr_auc"][model]
            common = [k for k in mine if k in base]
            if len(common) < 2:
                continue
            applicable = True
            if sum(mine[k] > base[k] for k in common) < 2 / 3 * len(common):
                return False
        return True if applicable else None

    gates["g5_logistic_beats_simple_baselines_both_folds"] = beats("L1_logistic")
    mean_pr = {k: float(np.mean([f["models"][k]["pr_auc"] for f in folds])) for k in ("G1_lightgbm", "G2_no_calendar", "L1_logistic")}
    if gates["g2_G1_beats_simple_baselines_both_folds"]:
        # если без календаря модель тоже побеждает baseline, а календарь даёт подозрительно много — берём G2
        selected = "G2_no_calendar" if (not gates["g3_no_calendar_shortcut"] and beats("G2_no_calendar")) else "G1_lightgbm"
        # при равенстве (±0,005 PR-AUC) предпочитаем более простую и устойчивую логистическую регрессию
        if gates["g5_logistic_beats_simple_baselines_both_folds"] and mean_pr["L1_logistic"] >= mean_pr[selected] - 0.005:
            selected = "L1_logistic"
        level = "validated_proxy_model"
    elif gates["g5_logistic_beats_simple_baselines_both_folds"]:
        selected, level = "L1_logistic", "validated_proxy_model"
    else:
        selected = max(base_means, key=base_means.get)
        level = "baseline_only"
    gates["g6_known_outcome_share"] = all(1 - f["unknown_share_selectable"] >= cfg["min_known_share_selectable"] for f in folds)
    gates["g7_stable_across_sensor_types"] = stable(selected) if level == "validated_proxy_model" else None
    return {"gates": gates, "selected": selected, "evidence_level": level, "abstain_reason": None,
            "simple_baseline_mean_pr_auc": base_means}


def score_kind(spec: dict[str, Any], decision: dict[str, Any], folds: dict[str, Any], cfg: dict[str, Any]) -> str:
    """Что отдаёт сервис: калиброванную вероятность обещаем только при подтверждённой модели и ECE ≤ порога."""
    if decision["evidence_level"] == "insufficient_events":
        return "abstain"
    if spec["family"] == "conditional_proxy_score":
        return "conditional_proxy_score"  # цензура длительности: на всю популяцию не калибруем (согласовано 10/Q1)
    sel = decision["selected"]
    eces = [f["models"][sel]["ece10"] for f in folds.values() if sel in f.get("models", {})]
    unknown = [f.get("unknown_share_selectable", 1.0) for f in folds.values()]
    # ECE на наблюдаемых строках не доказывает калибровку для всех каналов: требуем ещё малую долю unknown (GPT 14)
    if (decision["evidence_level"] == "validated_proxy_model" and eces and max(eces) <= cfg["ece_calibrated_max"]
            and max(unknown) <= cfg["max_unknown_share_calibrated"]):
        return "probability_calibrated"
    return "proxy_score"


def backend_contract(results: dict[str, Any], cov: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    out = {"schema_version": SCHEMA_VERSION, "mode": cfg["mode"],
           "window": "метка: события в [D+2; D+3) по признакам на конец D; решение метки не позже D+4",
           "cooldown_days": cfg["cooldown_days"], "targets": [],
           "data_quality_flags": [{"tz_item": "T1b", "incident_type": "clock_error_1970", "score_kind": "data_quality_flag",
                                   "source": "значение 01.01.1970 в журнале (FAQ: «сбилась дата»); признаки f_n_clock_1970_*",
                                   "not_a_failure_label": True}],
           "evidence_levels": {"validated_proxy_model": "модель лучше простых baseline в обоих фолдах (95% CI)",
                               "baseline_only": "отдаётся скор простого правила/приора",
                               "insufficient_events": "мало событий — abstain"}}
    for t, r in results.items():
        spec = TARGET_SPECS[t]
        d = r["decision"]
        last = r["folds"].get("fold_2024", {})
        sel = d.get("selected")
        m = last.get("models", {}).get(sel, {}) if sel else {}
        reasons = cov["targets"][t]["reasons"]
        abstain = {k: v for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])
                   if k not in ("positive", "negative", "negative_transient_only")}
        entry = {
            "target": t, "tz_item": spec["tz"], "incident_type": spec["incident_type"],
            "score_kind": score_kind(spec, d, r["folds"], cfg),
            "evidence_level": d["evidence_level"], "selected_model": sel,
            "coverage_labelled_share": round(cov["targets"][t]["labelled_share"], 4),
            "abstain_reasons_rows": abstain,
            "validation_fold_2024": ({"pr_auc_on_known": m.get("pr_auc"), "prevalence_on_known": last.get("prevalence_validation"),
                                      "unknown_share_selectable": last.get("unknown_share_selectable"),
                                      "brier": m.get("brier"), "ece10": m.get("ece10"),
                                      "budget_25_per_day": m.get("budget", {}).get("25")} if m else None),
            "not_a_confirmed_failure": True,
        }
        if spec["family"] == "conditional_proxy_score":
            lab = cov["targets"][t]["labelled_rows"]
            cen = reasons.get("censored_duration", 0)
            entry["censoring"] = {"censored_rows": cen, "censored_share_of_decidable": cen / max(lab + cen, 1),
                                  "note": "метрики — по нецензурированным строкам; для всей популяции это bounds, не оценка"}
        out["targets"].append(entry)
    return out


def run_targets_v3(cfg: dict[str, Any], log: Any = print) -> dict[str, Any]:
    import polars as pl

    t_start = time.time()
    out = Path(cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    parts, manifest = discover_panel(Path(cfg["input_dir"]), cfg["verify_sha256"])
    columns = pl.scan_parquet(parts).collect_schema().names()
    features = safe_features(manifest, columns)
    log(f"панель: {manifest['rows']:,} строк, частей {len(parts)}, признаков {len(features)}; режим {cfg['mode']}")
    cov = coverage(pl, parts, cfg["targets"], cfg)
    results = {}
    for t in cfg["targets"]:
        log(f"{t}:")
        frame = load_target(pl, parts, t, features, cfg)
        stress = load_stress(pl, parts, t, features, cfg)
        results[t] = run_target(pl, frame, t, features, cfg, log, stress=stress)
        del stress
        del frame
    contract = backend_contract(results, cov, cfg)
    status = "completed_smoke_non_comparable" if cfg["mode"] == "SMOKE" else "completed"
    payload = {"schema_version": SCHEMA_VERSION, "status": status, "mode": cfg["mode"],
               "panel_manifest": {"rows": manifest["rows"], "taxonomy_sha256": manifest["taxonomy_sha256"],
                                  "parts_sha256": [p["sha256"] for p in manifest["parts"]],
                                  "panel_config": manifest["panel_config"]},
               "protocol": {"folds": FOLDS,
                            "excluded_cutoff_dates": [str(x) for x in EXCLUDED], "load_end_exclusive": str(LOAD_END),
                            "features": features, "models": MODELS},
               "config": {k: v for k, v in cfg.items() if k not in ("input_dir", "output_dir")},
               "coverage": cov, "targets": results, "runtime_s": round(time.time() - t_start, 1)}
    (out / "results_targets_v3.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out / "backend_typed_scores_v3.json").write_text(json.dumps(contract, ensure_ascii=False, indent=2, default=str),
                                                      encoding="utf-8")
    (out / "summary_targets_v3_ru.md").write_text(summary_markdown(payload, contract), encoding="utf-8")
    return {"status": status, "runtime_s": payload["runtime_s"],
            "decisions": {t: r["decision"]["evidence_level"] for t, r in results.items()}}


def _f(x: Any, d: int = 3) -> str:
    return "—" if x is None else f"{x:.{d}f}"


def summary_markdown(payload: dict[str, Any], contract: dict[str, Any]) -> str:
    L = [f"# Ноутбук 15 — модели на целях панели v3 ({payload['mode']})", ""]
    if payload["mode"] == "SMOKE":
        L += ["**SMOKE:** часть каналов, мало деревьев — цифры не сравнимы с FULL.", ""]
    L += ["Метки — наблюдаемые события журнала, не подтверждённые отказы. 2021 и январь 2022 исключены; "
          "2025+ не загружается.", "", "## Итог по целям", "",
          "| цель | ТЗ | evidence_level | score_kind | модель | покрытие строк | PR-AUC 2023 | PR-AUC 2024 | unknown 2024 | precision@25/сут (cooldown) 2024, границы |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for c in contract["targets"]:
        r = payload["targets"][c["target"]]
        sel = c["selected_model"]
        pr = [_f(r["folds"][f].get("models", {}).get(sel, {}).get("pr_auc")) if sel else "—" for f in ("fold_2023", "fold_2024")]
        v = c["validation_fold_2024"] or {}
        b = v.get("budget_25_per_day") or {}
        L.append(f"| `{c['target']}` | {c['tz_item']} | **{c['evidence_level']}** | {c['score_kind']} | {sel or '—'} | "
                 f"{c['coverage_labelled_share']:.3f} | {pr[0]} | {pr[1]} | {_f(v.get('unknown_share_selectable'))} | "
                 f"{_f(b.get('precision_cooldown'))}–{_f(b.get('precision_upper_cooldown'))} |")
    for t, r in payload["targets"].items():
        L += ["", f"## `{t}`", ""]
        for fname, f in r["folds"].items():
            L += [f"**{fname}**: train {f['rows']['train']:,} (1: {f['rows']['train_pos']:,}), "
                  f"validation {f['rows']['validation']:,} (1: {f['rows']['validation_pos']:,})", ""]
            if "skipped" in f:
                L += [f"пропущен: {f['skipped']}", ""]
                continue
            L += [f"selectable в валидации: {f['rows']['validation_selectable']:,}, исход неизвестен: "
                  f"{f['rows']['validation_unknown']:,} ({f['unknown_share_selectable']:.1%}). PR-AUC/ROC/Brier/ECE — по известным; "
                  "P — нижняя–верхняя граница по всей selectable когорте, R — по известным положительным.", "",
                  "| модель | PR-AUC | ROC-AUC | Brier | ECE | P@10 | R@10 | P@25 cd | R@25 cd | слотов в unknown @25 cd |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
            for m, x in f["models"].items():
                b10, b25 = x["budget"].get("10", {}), x["budget"].get("25", {})
                L.append(f"| {m} | {_f(x['pr_auc'])} | {_f(x['roc_auc'])} | {_f(x['brier'], 4)} | {_f(x['ece10'], 4)} | "
                         f"{_f(b10.get('precision'))}–{_f(b10.get('precision_upper'))} | {_f(b10.get('recall'))} | "
                         f"{_f(b25.get('precision_cooldown'))}–{_f(b25.get('precision_upper_cooldown'))} | "
                         f"{_f(b25.get('recall_cooldown'))} | {b25.get('unknown_alerts_cooldown', 0):,} |")
            bb = f["best_simple_baseline"]
            bs = f[f"bootstrap_G1_lightgbm_vs_{bb}"]
            bl = f[f"bootstrap_L1_logistic_vs_{bb}"]
            L += ["", f"G1 − {bb}: ΔPR-AUC {_f(bs['mean'])} [{_f(bs['ci95_low'])}; {_f(bs['ci95_high'])}], повторов {bs['reps']}; "
                  f"L1 − {bb}: {_f(bl['mean'])} [{_f(bl['ci95_low'])}; {_f(bl['ci95_high'])}].",
                  "Топ признаков G1: " + ", ".join(f"{k} {v:.2f}" for k, v in list(f["importance_G1"].items())[:6]), ""]
            b50 = f["models"]["G1_lightgbm"]["budget"].get("50", {})
            L += [f"Top-50/сутки, G1, cooldown: слотов в unknown {b50.get('unknown_alerts_cooldown', 0):,} из {b50.get('alerts_cooldown', 0):,}; "
                  f"recall [{_f(b50.get('recall_low_cooldown'))}; {_f(b50.get('recall_up_cooldown'))}], "
                  f"precision [{_f(b50.get('precision_cooldown'))}; {_f(b50.get('precision_upper_cooldown'))}].", ""]
            if "competing_d1" in f:
                cd = f["competing_d1"]
                L += [f"Onset в D+1 (competing): {_f(cd['share_of_rows'])} строк, {_f(cd['share_of_positives'])} положительных. "
                      "PR-AUC для «первого onset» (onset в D+2 без onset в D+1): "
                      + ", ".join(f"{k.split('_')[0]} {_f(v)}" for k, v in cd["pr_auc_first_onset"].items()), ""]
        d = r["decision"]
        if r.get("stress_2021", {}).get("pr_auc"):
            st = r["stress_2021"]
            L += [f"Stress 2021 (модели fold_2024, в выборе не участвует): строк {st['rows']:,}, prevalence {_f(st['prevalence'], 4)}; PR-AUC "
                  + ", ".join(f"{k.split('_')[0]} {_f(v)}" for k, v in st["pr_auc"].items()), ""]
        L += ["Gates: " + ", ".join(f"{k} = {'—' if v is None else ('да' if v else 'нет')}" for k, v in d["gates"].items()), ""]
    L += ["", "## Как читать", "",
          "- `validated_proxy_model` — модель (LightGBM или логистическая регрессия) лучше простых baseline (приор по типу, правило) "
          "в обоих фолдах: нижняя граница 95% CI разницы PR-AUC > 0; при равенстве берётся логистическая регрессия.",
          "- `baseline_only` — модель не доказала преимущества; бэкенд отдаёт скор простого правила/приора.",
          "- `insufficient_events` — мало событий в валидации: бэкенд не выдаёт скор (abstain).",
          "- P@k — precision топ-k строк в сутки среди размеченных строк; `cd` — с cooldown по каналу.",
          ""]
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Синтетика для самопроверок и тестов
# ---------------------------------------------------------------------------
def synthetic_panel_v3(out_dir: Path, n_channels: int = 150, seed: int = 3, signal: float = 2.0,
                       end: date = date(2025, 1, 10), gas_features: bool = False) -> Path:
    """Панель со схемой v3 и встроенным сигналом (для тестов; не реальные данные).
    gas_features: добавить f_gas_n_7d / f_gas_last и строки above_threshold_at_D для T4 (тесты экспорта 16)."""
    import polars as pl

    rng = np.random.default_rng(seed)
    days = [date(2019, 1, 1) + timedelta(days=i) for i in range(0, (end - date(2019, 1, 1)).days, 3)]
    n = n_channels * len(days)
    ch = np.repeat(np.arange(n_channels), len(days))
    d = np.tile(np.array(days, dtype="datetime64[D]"), n_channels)
    types = np.array(["Состояние насоса", "КД Дверь", "Газовый датчик", "Состояние фазы"])[ch % 4]
    base = rng.poisson(0.3, n).astype(float)
    frame = {
        "d_channel_key": np.array([hashlib.sha256(f"s{c}".encode()).hexdigest()[:16] for c in range(n_channels)])[ch],
        "d_cutoff_date": d, "d_label_decision_end": d + np.timedelta64(4, "D"),
        "тип_датчика": types, "тип_инж_системы": np.where(ch % 2 == 0, "ВК", "ЭС"),
        "link_state": rng.choice(["O", "F", "A"], n, p=[0.9, 0.05, 0.05]),
        "power_state": rng.choice(["O", "F"], n, p=[0.9, 0.1]),
        "d_weekday": (d.astype("datetime64[D]").astype(int) + 3) % 7 + 1,
        "d_month": d.astype("datetime64[M]").astype(int) % 12 + 1,
        "f_n_events_7d": rng.poisson(50, n).astype(float),
    }
    for t, spec in TARGET_SPECS.items():
        for col in spec["rule"]:
            frame.setdefault(col, base + rng.poisson(0.2, n))
    noise = rng.normal(0, 1, n)
    for t, spec in TARGET_SPECS.items():
        x = frame[spec["rule"][0]]
        logit = -4.0 + signal * (x - x.mean()) / (x.std() + 1e-9) + 0.3 * noise
        y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(float)
        null = rng.random(n) < 0.3
        frame[t] = np.where(null, np.nan, y)
        frame["reason_" + t[len("target_"):]] = np.where(null, "unobserved_window", np.where(y == 1, "positive", "negative"))
    if gas_features:
        # объект = 8 каналов; ежегодное «молчание» объекта (как ППР): gas_max = null 12 суток в году
        obj = ch // 8
        frame["d_object_key"] = np.array([hashlib.sha256(f"o{o}".encode()).hexdigest()[:16] for o in range(n_channels // 8 + 1)])[obj]
        doy = (d.astype("datetime64[D]") - d.astype("datetime64[Y]")).astype(int)
        silent = np.abs(doy - (40 + 23 * (obj % 12))) < 6
        frame["gas_max"] = np.where(silent, np.nan, rng.uniform(0, 0.9, n))
        frame["f_gas_cross_n_30d"] = rng.poisson(0.3, n).astype(float)
        above = rng.random(n) < 0.1
        frame["f_gas_n_7d"] = rng.poisson(5, n).astype(float) + 1
        frame["f_gas_last"] = np.where(above, 1.5, rng.uniform(0, 0.9, n))
        frame["target_t4_gas_cross"] = np.where(above, np.nan, frame["target_t4_gas_cross"])
        frame["reason_t4_gas_cross"] = np.where(above, "above_threshold_at_D", frame["reason_t4_gas_cross"])
    panel = pl.DataFrame(frame).with_columns(
        pl.col("d_cutoff_date").cast(pl.Date), pl.col("d_label_decision_end").cast(pl.Date),
        *[pl.col(t).fill_nan(None).cast(pl.Int8) for t in TARGET_SPECS])
    panel_dir = Path(out_dir) / "event_panel_v3"
    panel_dir.mkdir(parents=True, exist_ok=True)
    part = panel_dir / "event_panel_v3_part00.parquet"
    panel.write_parquet(part)
    feats = [c for c in panel.columns if c.startswith("f_")] + CATEGORICAL + CALENDAR
    manifest = {"schema_version": SCHEMA_VERSION, "rows": panel.height, "taxonomy_sha256": "synthetic",
                "panel_config": {"synthetic": True}, "feature_columns": feats, "target_columns": list(TARGET_SPECS),
                "parts": [{"file": part.name, "sha256": file_sha256(part), "rows": panel.height}]}
    (panel_dir / "panel_manifest_v3.json").write_text(json.dumps(manifest), encoding="utf-8")
    return panel_dir


def run_targets_self_tests(work_dir: Path) -> dict[str, bool]:
    import polars as pl

    work_dir = Path(work_dir)
    rep: dict[str, bool] = {}
    y = np.array([0, 1, 0, 1, 0, 0])
    days = np.array([0, 0, 0, 1, 1, 1])
    ch = np.array(["a", "b", "c", "b", "a", "c"])
    s = np.array([0.1, 0.9, 0.2, 0.8, 0.3, 0.1])
    b = budget_curve(days, ch, y, s, [1], cooldown_days=3)["1"]
    rep["budget_top1_hits_both_days"] = b["precision"] == 1.0 and b["recall"] == 1.0
    rep["cooldown_blocks_repeat_channel"] = b["alerts_cooldown"] == 2 and b["recall_cooldown"] == 0.5
    bu = budget_curve(np.array([0, 0]), np.array(["a", "b"]), np.array([-1, 1]), np.array([0.9, 0.1]), [1], 3)["1"]
    rep["unknown_slot_counted_as_bounds"] = (bu["precision"] == 0.0 and bu["precision_upper"] == 1.0 and bu["unknown_alerts"] == 1
                                             and bu["recall_low"] == 0.0 and bu["recall_up"] == 0.5)
    try:
        safe_features({"feature_columns": ["f_x", "competing_link_onset_d1"]}, ["f_x", "competing_link_onset_d1"])
        rep["future_columns_rejected"] = False
    except ValueError:
        rep["future_columns_rejected"] = True
    frame = pl.DataFrame({"d_cutoff_date": [date(2022, 12, 25), date(2022, 12, 30), date(2023, 6, 29), date(2023, 7, 3)],
                          "d_label_decision_end": [date(2022, 12, 29), date(2023, 1, 3), date(2023, 7, 3), date(2023, 7, 7)]})
    tr, ca, va = split_fold(pl, frame, FOLDS[0])
    rep["purging_by_label_decision_end"] = tr.height == 1 and ca.height == 0 and va.height == 1
    root = work_dir / "synthetic_in"
    synthetic_panel_v3(root, n_channels=60)
    cfg = make_config_targets("SMOKE", {"input_dir": str(root), "output_dir": str(work_dir / "out"),
                                        "smoke_channel_share": 1, "targets": ["target_t2a_link_onset"],
                                        "bootstrap_reps": 10})
    res = run_targets_v3(cfg, log=lambda *a: None)
    rep["synthetic_end_to_end"] = res["status"] == "completed_smoke_non_comparable"
    text = (work_dir / "out" / "results_targets_v3.json").read_text(encoding="utf-8")
    keys = pl.read_parquet(root / "event_panel_v3" / "event_panel_v3_part00.parquet")["d_channel_key"].unique().to_list()
    rep["no_channel_keys_in_outputs"] = not any(k in text for k in keys)
    return rep
