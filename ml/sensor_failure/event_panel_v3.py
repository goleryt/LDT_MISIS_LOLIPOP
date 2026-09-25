"""Событийная панель v3: state machine по сырому журналу → панель (канал × сутки D) с раздельными целями.

Спецификация согласована в переписке Claude ↔ GPT (Drive, документы 05 → 12) и docs/EVENT_PANEL_V3_RU.md.
Главные правила:
- одна секунда канала = неупорядоченное множество значений; порядок строк CSV и ид_события порядком не считаются;
- признаки на конец D — только прошлое; метка окна [D+2; D+3) может смотреть вперёд не дальше D+4 (L = 24 ч);
- eligibility на конец D задаётся только состоянием на конец D; старт в D+1 — competing outcome, а не фильтр;
- неоднозначное → null с причиной, а не 0;
- цели разные и не смешиваются: T2a (onset «Неисправен» = потеря связи), T2b (потеря связи ≥ τ),
  T2c (onset «Обесточен»), T2c_sustained, T1a (технические/диапазонные значения), T4 (газ ≥ 1 %).
Ничто здесь не является подтверждённым физическим отказом.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "3.0"
EVENT_COLUMNS = ["ид_события", "ид_канала_данных", "дата", "время", "тревожное", "значение_датчика"]
CATALOGUE_COLUMNS = ["ид_канала_данных", "тип_инж_системы", "тип_датчика", "ид_объект"]
KEY_SALT = "ldt-misis-panel-v3:"

DEFAULT_CONFIG: dict[str, Any] = {
    "tau_minutes": 5,                 # порог «устойчивого» эпизода; чувствительность 1/5/30/60 — отдельными прогонами
    "confirm_hours": 24,              # L: самое позднее подтверждение метки, ч
    "active_lookback_days": 7,        # строка (канал, D) есть, если канал слал события в [D-6; D]
    "tech_clean_days": 7,             # T1a: onset только после ≥ 7 суток без технических значений
    "numeric_history_days": 30,       # T1a: канал должен слать числа в последние 30 суток
    "window_offsets_days": [7, 30],   # окна скользящих признаков
    "service_as_unknown": True,       # «Неопределен» = U для связи (основная версия); False — sensitivity (GPT 16/Q1)
    "power_ok_from_function": False,  # sensitivity: сообщения функции канала (норма/событие/число) считаются O питания
}

# заранее объявленные sensitivity-варианты разметки (выбор между ними не делается по validation-метрикам)
SENSITIVITY_VARIANTS = {"service_neutral": {"service_as_unknown": False},
                        "power_ok_from_function": {"power_ok_from_function": True}}

LINK_STATES = ("O", "F", "A")  # ok / fault / ambiguous
TARGETS = ["target_t2a_link_onset", "target_t2b_link_sustained", "target_t2c_power_onset",
           "target_t2c_power_sustained", "target_t1a_tech_value", "target_t4_gas_cross"]
BASE_FEATURES = ["n_events", "n_alarm", "n_link_fault", "n_power_off", "n_service", "n_tech_like", "n_numeric",
                 "n_multi_value_seconds", "num_mean", "num_min", "num_max", "num_std", "num_last", "gas_max", "gas_last",
                 "link_state", "power_state", "d_weekday", "d_month"]


# ---------------------------------------------------------------------------
# 0. Таксономия и ключи
# ---------------------------------------------------------------------------
def load_taxonomy(path: Path) -> dict[str, Any]:
    tax = json.loads(Path(path).read_text(encoding="utf-8"))
    seen: dict[str, str] = {}
    for cls, values in tax["text_classes"].items():
        for v in values:
            if v in seen and seen[v] != cls:
                raise ValueError(f"значение {v!r} в двух классах: {seen[v]} и {cls}")
            seen[v] = cls
    tax["_value_to_class"] = seen
    tax["_sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return tax


def pseudo_key(raw: str | None) -> str | None:
    if raw is None:
        return None
    return hashlib.sha256((KEY_SALT + str(raw)).encode("utf-8")).hexdigest()[:16]


def key_map(pl: Any, ids: Iterable[str], name: str) -> Any:
    ids = sorted({str(i) for i in ids if i is not None})
    return pl.DataFrame({"raw": ids, name: [pseudo_key(i) for i in ids]})


# ---------------------------------------------------------------------------
# 1. Классификация событий
# ---------------------------------------------------------------------------
def classify_events(pl: Any, frame: Any, tax: dict[str, Any], catalogue: Any) -> Any:
    """frame: сырые колонки журнала (строки). Возвращает ch, t, v, alarm, num, cls, is_gas, тип_*."""
    num_cfg, date_cfg = tax["numeric"], tax["date_like"]
    value = pl.col("значение_датчика").fill_null("")
    num = value.str.replace(",", ".", literal=True).cast(pl.Float64, strict=False)
    t = pl.concat_str(["дата", "время"], separator=" ").str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S", strict=False)
    out = (
        frame.join(catalogue, on="ид_канала_данных", how="left")
        .with_columns(
            pl.col("ид_канала_данных").alias("ch"), t.alias("t"), value.alias("v"), num.alias("num"),
            pl.col("тревожное").fill_null("").str.to_lowercase().is_in(["t", "true"]).alias("alarm"),
            (pl.col("тип_датчика") == num_cfg["gas_sensor_type"]).fill_null(False).alias("is_gas"),
        )
        .filter(pl.col("t").is_not_null())
    )
    is_date = pl.col("v").str.contains(date_cfg["regex"])
    parsed_date = pl.col("v").str.slice(0, 19).str.strptime(pl.Datetime("us"), "%d.%m.%Y %H:%M:%S", strict=False)
    tol = int(date_cfg["duplicate_timestamp_tolerance_seconds"])
    text_cls = pl.col("v").replace_strict(tax["_value_to_class"], default="unknown_value", return_dtype=pl.String)
    cls = (
        pl.when(pl.col("num").is_not_null() & pl.col("num").is_in(num_cfg["technical_value_candidates"])).then(pl.lit("tech_value"))
        .when(pl.col("num").is_not_null() & pl.col("is_gas")
              & ((pl.col("num") < num_cfg["gas_out_of_range"]["below"]) | (pl.col("num") > num_cfg["gas_out_of_range"]["above"])))
        .then(pl.lit("gas_out_of_range"))
        .when(pl.col("num").is_not_null()).then(pl.lit("numeric"))
        .when(is_date & pl.col("v").str.starts_with(date_cfg["clock_1970_prefix"])).then(pl.lit("clock_1970"))
        .when(is_date & ((parsed_date - pl.col("t")).dt.total_seconds().abs() <= tol)).then(pl.lit("dup_timestamp"))
        .when(is_date).then(pl.lit("date_other"))
        .when(pl.col("v") == "").then(pl.lit("empty_value"))
        .otherwise(text_cls)
    )
    return out.with_columns(cls.alias("cls")).select(
        "ch", "t", "v", "alarm", "num", "cls", "is_gas", "тип_датчика", "тип_инж_системы", "ид_объект")


# ---------------------------------------------------------------------------
# 2. Секундный уровень и точки смены состояния (RLE)
# ---------------------------------------------------------------------------
def second_table(pl: Any, ev: Any, tax: dict[str, Any]) -> Any:
    """Одна строка = (канал, секунда). Порядок внутри секунды не используется.
    Для каждого потока (связь, питание) секунда: F — только отказ, O — только рабочее состояние того же потока,
    A — отказ и O вместе или любое неизвестное (U) этого потока; null — секунда не несёт сведений о потоке."""
    streams = tax["stream_mapping"]["streams"]
    aggs = [pl.col("v").n_unique().alias("n_values"), (pl.col("cls") == "link_fault").any().alias("has_fault")]
    for name, st in streams.items():
        aggs += [pl.col("cls").is_in(st["fault"]).any().alias(f"_{name}_f"),
                 pl.col("cls").is_in(st["ok"]).any().alias(f"_{name}_o"),
                 pl.col("cls").is_in(st["unknown"]).any().alias(f"_{name}_u")]
    sec = ev.group_by("ch", "t").agg(*aggs)
    cols = []
    for name in streams:
        f, o, u = pl.col(f"_{name}_f"), pl.col(f"_{name}_o"), pl.col(f"_{name}_u")
        override = bool(streams[name].get("unknown_overrides", True))
        u_wins = u if override else (u & ~f & ~o)
        cols.append(pl.when(f & o).then(pl.lit("A")).when(u_wins).then(pl.lit("A"))
                    .when(f).then(pl.lit("F")).when(o).then(pl.lit("O")).otherwise(None).alias(f"{name}_cls"))
        cols.append(pl.when(f & o).then(pl.lit("conflict")).when(u_wins).then(pl.lit("unknown")).otherwise(None)
                    .alias(f"{name}_a_cause"))
    return sec.with_columns(cols).drop([c for c in sec.columns if c.startswith("_")])


def change_points(pl: Any, sec: Any, cls_col: str) -> Any:
    """RLE решающих секунд: строки, где класс сменился (по каналу, по времени)."""
    d = sec.filter(pl.col(cls_col).is_not_null()).select("ch", "t", pl.col(cls_col).alias("cls")).sort("ch", "t")
    return rle(pl, d)


def rle(pl: Any, d: Any) -> Any:
    d = d.sort("ch", "t")
    prev = pl.col("cls").shift(1).over("ch")
    return d.filter(prev.is_null() | (pl.col("cls") != prev)).select("ch", "t", "cls")


# ---------------------------------------------------------------------------
# 3. Эпизоды
# ---------------------------------------------------------------------------
def episodes(pl: Any, cp: Any, data_end: datetime, tau_minutes: float) -> Any:
    """Эпизод = RLE-блок класса F. onset_type: strict (перед ним однозначное O) или ambiguous.
    Длительность: до следующей точки смены. Следующая O → exact; A или конец данных → цензура (нижняя граница).
    sustained = 1 только при однозначном закрытии (O того же потока) после t0 + τ: повторы «Неисправен» и тишина
    непрерывность не доказывают (GPT 14, C7); незакрытый эпизод → null."""
    cp = cp.sort("ch", "t").with_columns(
        pl.col("cls").shift(1).over("ch").alias("prev_cls"),
        pl.col("cls").shift(-1).over("ch").alias("next_cls"),
        pl.col("t").shift(-1).over("ch").alias("next_t"),
    )
    tau_s = tau_minutes * 60.0
    ep = cp.filter(pl.col("cls") == "F").with_columns(
        pl.when(pl.col("prev_cls") == "O").then(pl.lit("strict")).otherwise(pl.lit("ambiguous")).alias("onset_type"),
        (pl.col("next_cls") == "O").fill_null(False).alias("exact"),
        pl.col("next_t").fill_null(pl.lit(data_end)).alias("end_t"),
    ).with_columns(
        (pl.col("end_t") - pl.col("t")).dt.total_seconds().cast(pl.Float64).alias("duration_s"),
    ).with_columns(
        pl.when(pl.col("exact") & (pl.col("duration_s") >= tau_s)).then(pl.lit(1, pl.Int8))
        .when(pl.col("exact")).then(pl.lit(0, pl.Int8))
        .otherwise(None).alias("sustained"),
    )
    return ep.select("ch", pl.col("t").alias("onset_t"), "onset_type", "exact", "end_t", "duration_s", "sustained")


# ---------------------------------------------------------------------------
# 4. Дневные агрегаты
# ---------------------------------------------------------------------------
COUNT_CLASSES = ["link_fault", "power_off", "power_on", "power_degraded", "device_off", "service",
                 "undefined_measurement", "object_summary", "security_mode", "flood", "event_alarm", "normal",
                 "numeric", "tech_value", "gas_out_of_range", "clock_1970", "dup_timestamp", "date_other",
                 "unknown_value", "empty_value"]


def daily_aggregates(pl: Any, ev: Any, sec: Any, tax: dict[str, Any]) -> Any:
    thr = tax["numeric"]["gas_threshold_percent"]
    low = tax["numeric"]["gas_band_low"]
    warn = tax["numeric"]["gas_warning_percent"]
    # порядок внутри группы = время; в одной секунде значения не упорядочены — берём детерминированно (по значению)
    ev = ev.sort("ch", "t", "num", nulls_last=False, maintain_order=True).with_columns(pl.col("t").dt.date().alias("day"))
    numeric = pl.col("cls") == "numeric"
    gas = numeric & pl.col("is_gas")
    agg = ev.group_by("ch", "day").agg(
        pl.len().alias("n_events"),
        pl.col("alarm").sum().alias("n_alarm"),
        *[(pl.col("cls") == c).sum().alias(f"n_{c}") for c in COUNT_CLASSES],
        pl.col("num").filter(numeric).mean().alias("num_mean"),
        pl.col("num").filter(numeric).min().alias("num_min"),
        pl.col("num").filter(numeric).max().alias("num_max"),
        pl.col("num").filter(numeric).std().alias("num_std"),
        pl.col("num").filter(numeric).last().alias("num_last"),
        pl.col("num").filter(gas).max().alias("gas_max"),
        pl.col("num").filter(gas).count().alias("gas_n"),
        (gas & (pl.col("num") >= low) & (pl.col("num") < thr)).sum().alias("gas_band_n"),
        (gas & (pl.col("num") >= thr)).sum().alias("gas_ge_thr_n"),
        (gas & (pl.col("num") >= warn)).sum().alias("gas_ge_warn_n"),
        pl.col("num").filter(gas).last().alias("gas_last"),
        # последняя газовая секунда суток содержит значения по обе стороны порога → сторона на конец D неизвестна (GPT 42)
        ((pl.col("num").filter(gas & (pl.col("t") == pl.col("t").filter(gas).max())).min() < thr)
         & (pl.col("num").filter(gas & (pl.col("t") == pl.col("t").filter(gas).max())).max() >= thr)).alias("gas_last_mixed"),
    )
    s = sec.with_columns(pl.col("t").dt.date().alias("day")).group_by("ch", "day").agg(
        (pl.col("n_values") > 1).sum().alias("n_multi_value_seconds"),
        (pl.col("link_cls") == "F").sum().alias("n_link_fault_seconds"),
        (pl.col("link_cls") == "A").sum().alias("n_link_ambiguous_seconds"),
        (pl.col("power_cls") == "F").sum().alias("n_power_off_seconds"),
    )
    return agg.join(s, on=["ch", "day"], how="left")


def gas_crossings(pl: Any, ev: Any, carry: Any, thr: float) -> tuple[Any, Any]:
    """Строгое пересечение порога на секундном уровне (секунда = множество значений без порядка, как для состояний):
    strict — все показания секунды ≥ thr, а все показания предыдущей секунды того же канала < thr;
    неоднозначно (cross_unknown) — в секунде есть значения по обе стороны порога, либо предыдущая секунда такая,
    либо предыдущего показания нет. Раньше показания одной секунды сортировались по значению, и пара 0 / 2,55
    в одну секунду давала ложный strict crossing (GPT 37).
    carry: последняя газовая секунда каждого канала из предыдущего года (ch, t, mn, mx)."""
    g = (ev.filter((pl.col("cls") == "numeric") & pl.col("is_gas"))
         .group_by("ch", "t").agg(pl.col("num").min().alias("mn"), pl.col("num").max().alias("mx")))
    both = pl.concat([carry.select("ch", "t", "mn", "mx").with_columns(pl.lit(True).alias("_carry")),
                      g.with_columns(pl.lit(False).alias("_carry"))], how="vertical").sort("ch", "t", "_carry",
                                                                                          descending=[False, False, True])
    pmn, pmx = pl.col("mn").shift(1).over("ch"), pl.col("mx").shift(1).over("ch")
    straddle = (pl.col("mn") < thr) & (pl.col("mx") >= thr)
    prev_straddle = (pmn < thr) & (pmx >= thr)
    x = both.with_columns(
        ((pl.col("mn") >= thr) & (pmx < thr)).fill_null(False).alias("cross"),
        ((pl.col("mx") >= thr) & (pmx.is_null() | straddle | ((pl.col("mn") >= thr) & prev_straddle.fill_null(False))))
        .fill_null(False).alias("cross_unknown_prev"))
    x = x.filter(~pl.col("_carry"))
    daily = x.with_columns(pl.col("t").dt.date().alias("day")).group_by("ch", "day").agg(
        pl.col("cross").sum().alias("gas_cross_n"), pl.col("cross_unknown_prev").sum().alias("gas_cross_unknown_n"))
    new_carry = (pl.concat([carry.select("ch", "t", "mn", "mx"), g], how="vertical").sort("ch", "t")
                 .group_by("ch", maintain_order=True).agg(pl.col("t").last(), pl.col("mn").last(), pl.col("mx").last()))
    return daily, new_carry


# ---------------------------------------------------------------------------
# 5. Сборка панели
# ---------------------------------------------------------------------------
def _shift_days(pl: Any, frame: Any, cols: list[str], offset: int, suffix: str) -> Any:
    """Факты дня X → строки D = X − offset."""
    return frame.select("ch", (pl.col("day") - pl.duration(days=offset)).alias("day"),
                        *[pl.col(c).alias(f"{c}{suffix}") for c in cols])


def build_panel_from_parts(pl: Any, daily: Any, link_cp: Any, power_cp: Any, gas_daily: Any,
                           meta: Any, data_end: datetime, config: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    tau = float(config["tau_minutes"])
    L = int(config["confirm_hours"])
    lookback = int(config["active_lookback_days"])
    data_end_day = data_end.date()

    link_ep = episodes(pl, link_cp, data_end, tau)
    power_ep = episodes(pl, power_cp, data_end, tau)

    daily = daily.join(gas_daily, on=["ch", "day"], how="left").with_columns(
        pl.col("gas_cross_n").fill_null(0), pl.col("gas_cross_unknown_n").fill_null(0))

    # грид: (канал, D), если канал слал события в [D-lookback+1; D]
    grid = (daily.select("ch", "day")
            .with_columns(pl.int_ranges(0, lookback).alias("_k")).explode("_k")
            .with_columns((pl.col("day") + pl.duration(days=pl.col("_k"))).alias("day"))
            .filter(pl.col("day") <= pl.lit(data_end_day))
            .select("ch", "day").unique().sort("ch", "day"))

    count_cols = [c for c in daily.columns if c.startswith("n_") or c in ("gas_n", "gas_band_n", "gas_ge_thr_n",
                                                                               "gas_ge_warn_n", "gas_cross_n")]
    panel = grid.join(daily, on=["ch", "day"], how="left").with_columns(
        [pl.col(c).fill_null(0) for c in count_cols]).sort("ch", "day")

    # эпизоды по дням: onset-день (для меток и признаков) и день завершения (для признаков «прошлых эпизодов»)
    def per_day(ep: Any, prefix: str, cp: Any) -> tuple[Any, Any, Any]:
        on = ep.with_columns(pl.col("onset_t").dt.date().alias("day")).group_by("ch", "day").agg(
            (pl.col("onset_type") == "strict").sum().alias(f"{prefix}_onset_strict"),
            (pl.col("onset_type") == "ambiguous").sum().alias(f"{prefix}_onset_ambiguous"),
            ((pl.col("onset_type") == "strict") & (pl.col("sustained") == 1)).sum().alias(f"{prefix}_onset_sustained"),
            ((pl.col("onset_type") == "strict") & (pl.col("sustained") == 0)).sum().alias(f"{prefix}_onset_transient"),
            ((pl.col("onset_type") == "strict") & pl.col("sustained").is_null()).sum().alias(f"{prefix}_onset_censored"),
        )
        done = ep.filter(pl.col("exact")).with_columns(pl.col("end_t").dt.date().alias("day")).group_by("ch", "day").agg(
            (pl.col("sustained") == 1).sum().alias(f"{prefix}_completed_long"),
            (pl.col("sustained") == 0).sum().alias(f"{prefix}_completed_short"),
        )
        # неоднозначные секунды (A-блоки): переход мог быть скрыт — окно с таким блоком не отрицательное (GPT 14, C2/C12)
        amb = cp.filter(pl.col("cls") == "A").with_columns(pl.col("t").dt.date().alias("day")).group_by("ch", "day").agg(
            pl.len().cast(pl.Int64).alias(f"{prefix}_ambiguous_block"))
        return on, done, amb

    link_on, link_done, link_amb = per_day(link_ep, "link", link_cp)
    power_on, power_done, power_amb = per_day(power_ep, "power", power_cp)
    for part in (link_on, link_done, power_on, power_done, link_amb, power_amb):
        cols = [c for c in part.columns if c not in ("ch", "day")]
        panel = panel.join(part, on=["ch", "day"], how="left").with_columns([pl.col(c).fill_null(0) for c in cols])

    # скользящие признаки (только прошлое, включая D)
    roll_src = ["n_events", "n_alarm", "n_link_fault", "n_power_off", "n_service", "n_device_off",
                "n_undefined_measurement", "n_tech_value", "n_gas_out_of_range", "n_clock_1970", "n_dup_timestamp",
                "n_date_other", "n_unknown_value", "n_flood", "n_event_alarm", "n_numeric", "n_multi_value_seconds",
                "n_link_fault_seconds", "n_link_ambiguous_seconds", "n_power_off_seconds",
                "link_onset_strict", "link_onset_ambiguous", "power_onset_strict",
                "link_completed_long", "link_completed_short", "power_completed_long", "power_completed_short",
                "gas_n", "gas_band_n", "gas_ge_thr_n", "gas_ge_warn_n", "gas_cross_n"]
    panel = panel.with_columns((pl.col("n_events") > 0).cast(pl.Int32).alias("active_day"),
                               (pl.col("n_tech_value") + pl.col("n_gas_out_of_range") + pl.col("n_undefined_measurement"))
                               .alias("n_tech_like"),
                               (pl.col("n_numeric") + pl.col("n_undefined_measurement") + pl.col("n_tech_value")
                                + pl.col("n_gas_out_of_range")).alias("n_measurement"))
    roll_exprs = []
    for w in config["window_offsets_days"]:
        for c in roll_src + ["active_day", "n_tech_like", "n_measurement"]:
            # polars < 1.3x не принимает null во входе rolling_*_by: счётчики без событий = 0
            roll_exprs.append(pl.col(c).fill_null(0).rolling_sum_by("day", window_size=f"{w}d", closed="right")
                              .over("ch").alias(f"f_{c}_{w}d"))
        # максимум газа: дни без газовых чисел → −∞ во входе, окно без чисел → null на выходе
        gmax = pl.col("gas_max").fill_null(float("-inf")).rolling_max_by("day", window_size=f"{w}d", closed="right").over("ch")
        roll_exprs.append(pl.when(gmax == float("-inf")).then(None).otherwise(gmax).alias(f"f_gas_max_{w}d"))
    panel = panel.sort("ch", "day").with_columns(roll_exprs)
    # последнее газовое/числовое значение на конец D (forward fill по грид-строкам канала)
    panel = panel.with_columns(pl.col("gas_last").forward_fill().over("ch").alias("f_gas_last"),
                               pl.col("num_last").forward_fill().over("ch").alias("f_num_last"),
                               pl.when(pl.col("gas_last").is_not_null()).then(pl.col("gas_last_mixed").fill_null(False))
                               .forward_fill().over("ch").fill_null(False).alias("_gas_last_mixed"))

    # состояния на конец D (as-of по точкам смены)
    cutoff = (pl.col("day").cast(pl.Datetime("us")) + pl.duration(days=1) - pl.duration(microseconds=1))
    panel = panel.with_columns(cutoff.alias("_cutoff_t")).sort("_cutoff_t")
    for name, cp in (("link", link_cp), ("power", power_cp)):
        c = cp.select("ch", pl.col("t").alias(f"_{name}_t"), pl.col("cls").alias(f"{name}_state")).sort(f"_{name}_t")
        panel = panel.join_asof(c, left_on="_cutoff_t", right_on=f"_{name}_t", by="ch", strategy="backward")
        panel = panel.with_columns(
            ((pl.col("_cutoff_t") - pl.col(f"_{name}_t")).dt.total_seconds() / 86400.0).alias(f"f_{name}_state_age_days"))
        last_on = (link_ep if name == "link" else power_ep).filter(pl.col("onset_type") == "strict").select(
            "ch", pl.col("onset_t").alias(f"_{name}_last_onset")).sort(f"_{name}_last_onset")
        panel = panel.join_asof(last_on, left_on="_cutoff_t", right_on=f"_{name}_last_onset", by="ch",
                                strategy="backward").with_columns(
            ((pl.col("_cutoff_t") - pl.col(f"_{name}_last_onset")).dt.total_seconds() / 86400.0)
            .alias(f"f_days_since_{name}_onset"))
    panel = panel.sort("ch", "day")

    # факты будущих дней для меток
    fact_cols = ["n_events", "link_onset_strict", "link_onset_ambiguous", "link_onset_sustained", "link_onset_censored",
                 "link_onset_transient", "power_onset_strict", "power_onset_ambiguous", "power_onset_sustained",
                 "power_onset_censored", "power_onset_transient", "link_ambiguous_block", "power_ambiguous_block",
                 "n_tech_like", "n_measurement", "gas_n",
                 "gas_cross_n", "gas_cross_unknown_n"]
    # каждый наблюдённый день есть в гриде (k = 0), поэтому факты любого дня с событиями — в panel
    facts = panel.select("ch", "day", *fact_cols)
    d1 = _shift_days(pl, facts, ["link_onset_strict", "link_onset_ambiguous", "power_onset_strict",
                                 "power_onset_ambiguous", "gas_cross_n"], 1, "_d1")
    d2 = _shift_days(pl, facts, fact_cols, 2, "_d2")
    d3 = _shift_days(pl, facts, ["n_events"], 3, "_d3")
    panel = panel.join(d1, on=["ch", "day"], how="left").join(d2, on=["ch", "day"], how="left") \
                 .join(d3, on=["ch", "day"], how="left")
    fut_cols = [c for c in panel.columns if c.endswith(("_d1", "_d2", "_d3"))]
    panel = panel.with_columns([pl.col(c).fill_null(0) for c in fut_cols])

    in_data = (pl.col("day") + pl.duration(days=3)) <= pl.lit(data_end_day)  # окно + L внутри данных
    observed = in_data & ((pl.col("n_events_d2") + pl.col("n_events_d3")) > 0)

    def onset_target(prefix: str, state_col: str, sustained: bool) -> tuple[Any, Any]:
        strict = pl.col(f"{prefix}_onset_strict_d2")
        amb = pl.col(f"{prefix}_onset_ambiguous_d2") + pl.col(f"{prefix}_ambiguous_block_d2")
        eligible = pl.col(state_col) == "O"
        if not sustained:
            label = (pl.when(~eligible.fill_null(False)).then(None)
                     .when(~in_data).then(None)
                     .when(strict > 0).then(pl.lit(1))
                     .when(amb > 0).then(None)
                     .when(observed).then(pl.lit(0))
                     .otherwise(None))
            reason = (pl.when(pl.col(state_col).is_null()).then(pl.lit("no_state_history"))
                      .when(~eligible).then(pl.lit("state_not_ok_at_D"))
                      .when(~in_data).then(pl.lit("window_beyond_data"))
                      .when(strict > 0).then(pl.lit("positive"))
                      .when(amb > 0).then(pl.lit("ambiguous_onset"))
                      .when(observed).then(pl.lit("negative"))
                      .otherwise(pl.lit("unobserved_window")))
        else:
            sus, cen, tra = (pl.col(f"{prefix}_onset_sustained_d2"), pl.col(f"{prefix}_onset_censored_d2"),
                             pl.col(f"{prefix}_onset_transient_d2"))
            label = (pl.when(~eligible.fill_null(False)).then(None)
                     .when(~in_data).then(None)
                     .when(sus > 0).then(pl.lit(1))
                     .when(cen > 0).then(None)
                     .when(amb > 0).then(None)
                     .when(observed).then(pl.lit(0))  # включая только кратковременные (transient) onset
                     .otherwise(None))
            reason = (pl.when(pl.col(state_col).is_null()).then(pl.lit("no_state_history"))
                      .when(~eligible).then(pl.lit("state_not_ok_at_D"))
                      .when(~in_data).then(pl.lit("window_beyond_data"))
                      .when(sus > 0).then(pl.lit("positive"))
                      .when(cen > 0).then(pl.lit("censored_duration"))
                      .when(amb > 0).then(pl.lit("ambiguous_onset"))
                      .when(observed & (tra > 0)).then(pl.lit("negative_transient_only"))
                      .when(observed).then(pl.lit("negative"))
                      .otherwise(pl.lit("unobserved_window")))
        return label.cast(pl.Int8), reason

    targets = {}
    reasons = {}
    for name, prefix, state, sus in (("target_t2a_link_onset", "link", "link_state", False),
                                     ("target_t2b_link_sustained", "link", "link_state", True),
                                     ("target_t2c_power_onset", "power", "power_state", False),
                                     ("target_t2c_power_sustained", "power", "power_state", True)):
        lab, rea = onset_target(prefix, state, sus)
        targets[name], reasons[name] = lab, rea

    # T1a: технические/диапазонные значения после ≥ tech_clean_days чистых суток
    clean = int(config["tech_clean_days"])
    hist = int(config["numeric_history_days"])
    panel = panel.with_columns(
        pl.col("n_tech_like").fill_null(0).rolling_sum_by("day", window_size=f"{clean}d", closed="right").over("ch").alias("_tech_recent"),
        pl.col("n_measurement").fill_null(0).rolling_sum_by("day", window_size=f"{hist}d", closed="right").over("ch").alias("_meas_hist"),
    )
    t1_elig = (pl.col("_meas_hist") > 0) & (pl.col("_tech_recent") == 0)
    targets["target_t1a_tech_value"] = (pl.when(~t1_elig | ~in_data).then(None)
                                        .when(pl.col("n_tech_like_d2") > 0).then(pl.lit(1))
                                        .when(pl.col("n_measurement_d2") > 0).then(pl.lit(0))
                                        .otherwise(None)).cast(pl.Int8)
    reasons["target_t1a_tech_value"] = (pl.when(pl.col("_meas_hist") == 0).then(pl.lit("no_measurements_30d"))
                                        .when(pl.col("_tech_recent") > 0).then(pl.lit("recent_tech_value"))
                                        .when(~in_data).then(pl.lit("window_beyond_data"))
                                        .when(pl.col("n_tech_like_d2") > 0).then(pl.lit("positive"))
                                        .when(pl.col("n_measurement_d2") > 0).then(pl.lit("negative"))
                                        .otherwise(pl.lit("unobserved_window")))

    # T4: газ — строгое пересечение 1 % в окне; канал газовый, последнее показание на конец D < порога
    thr = config["gas_threshold_percent"]
    gas_elig = (pl.col("f_gas_n_7d") > 0) & (pl.col("f_gas_last") < thr) & ~pl.col("_gas_last_mixed")
    targets["target_t4_gas_cross"] = (pl.when(~gas_elig.fill_null(False) | ~in_data).then(None)
                                      .when(pl.col("gas_cross_n_d2") > 0).then(pl.lit(1))
                                      .when(pl.col("gas_cross_unknown_n_d2") > 0).then(None)
                                      .when(pl.col("gas_n_d2") > 0).then(pl.lit(0))
                                      .otherwise(None)).cast(pl.Int8)
    reasons["target_t4_gas_cross"] = (pl.when(pl.col("f_gas_n_7d").fill_null(0) == 0).then(pl.lit("not_gas_stream"))
                                      .when(pl.col("_gas_last_mixed")).then(pl.lit("ambiguous_last_reading_at_D"))
                                      .when(pl.col("f_gas_last") >= thr).then(pl.lit("above_threshold_at_D"))
                                      .when(~in_data).then(pl.lit("window_beyond_data"))
                                      .when(pl.col("gas_cross_n_d2") > 0).then(pl.lit("positive"))
                                      .when(pl.col("gas_cross_unknown_n_d2") > 0).then(pl.lit("unknown_previous_reading"))
                                      .when(pl.col("gas_n_d2") > 0).then(pl.lit("negative"))
                                      .otherwise(pl.lit("unobserved_window")))

    panel = panel.with_columns(
        **targets, **{f"reason_{k[len('target_'):]}": v for k, v in reasons.items()},
        competing_link_onset_d1=(pl.col("link_onset_strict_d1") + pl.col("link_onset_ambiguous_d1") > 0),
        competing_power_onset_d1=(pl.col("power_onset_strict_d1") + pl.col("power_onset_ambiguous_d1") > 0),
        competing_gas_cross_d1=(pl.col("gas_cross_n_d1") > 0),
    )

    # мета: тип, объект, псевдоним ключей; календарь
    panel = panel.join(meta, on="ch", how="left").with_columns(
        pl.col("day").alias("d_cutoff_date"),
        (pl.col("day") + pl.duration(days=2)).alias("d_target_start_date"),
        (pl.col("day") + pl.duration(days=3)).alias("d_target_end_date_exclusive"),
        (pl.col("day") + pl.duration(days=3) + pl.duration(hours=L)).alias("d_label_decision_end"),
        pl.col("day").dt.year().alias("d_year"),
        pl.col("day").dt.weekday().alias("d_weekday"),
        pl.col("day").dt.month().alias("d_month"),
    )
    keys = key_map(pl, panel["ch"].unique().to_list(), "d_channel_key")
    objs = key_map(pl, panel["ид_объект"].drop_nulls().unique().to_list(), "d_object_key")
    panel = (panel.join(keys, left_on="ch", right_on="raw", how="left")
             .join(objs, left_on="ид_объект", right_on="raw", how="left"))

    feature_cols = [c for c in panel.columns if c.startswith("f_")] + BASE_FEATURES
    target_cols = list(targets)
    assert target_cols == TARGETS
    keep = (["d_channel_key", "d_object_key", "d_cutoff_date", "d_target_start_date", "d_target_end_date_exclusive",
             "d_label_decision_end", "d_year", "тип_датчика", "тип_инж_системы"] + feature_cols + target_cols
            + [f"reason_{k[len('target_'):]}" for k in target_cols]
            + ["competing_link_onset_d1", "competing_power_onset_d1", "competing_gas_cross_d1"])
    out = panel.select(keep).sort("d_channel_key", "d_cutoff_date")

    durations = pl.concat([
        e.select(pl.lit(n).alias("kind"), "onset_type", "exact", "duration_s", "sustained")
        for n, e in (("link", link_ep), ("power", power_ep))], how="vertical")
    return out, {"rows": out.height, "channels": out["d_channel_key"].n_unique(), "_episode_durations": durations}


# ---------------------------------------------------------------------------
# 6. Аудит (только агрегаты)
# ---------------------------------------------------------------------------
def final_audit(pl: Any, panel_lf: Any, durations: Any) -> dict[str, Any]:
    def ep_stats(kind: str) -> dict[str, Any]:
        ep = durations.filter(pl.col("kind") == kind)
        s = ep.filter(pl.col("onset_type") == "strict")
        dur = s.filter(pl.col("exact"))["duration_s"]
        return {
            "episodes": ep.height, "strict_onsets": s.height,
            "ambiguous_onsets": int((ep["onset_type"] == "ambiguous").sum()),
            "strict_exact": dur.len(), "strict_censored": int((~s["exact"]).sum()),
            "exact_duration_s_quantiles": ({str(q): float(dur.quantile(q)) for q in (0.1, 0.5, 0.9, 0.99)} if dur.len() else None),
            "sustained_1": int((s["sustained"] == 1).sum()), "sustained_0": int((s["sustained"] == 0).sum()),
            "sustained_null": int(s["sustained"].is_null().sum()),
        }

    head = panel_lf.select(pl.len().alias("rows"), pl.col("d_channel_key").n_unique().alias("channels"),
                           pl.col("d_cutoff_date").min().alias("dmin"), pl.col("d_cutoff_date").max().alias("dmax")).collect()
    out: dict[str, Any] = {"rows": int(head["rows"][0]), "channels": int(head["channels"][0]),
                           "date_min": str(head["dmin"][0]), "date_max": str(head["dmax"][0]),
                           "link_episodes": ep_stats("link"), "power_episodes": ep_stats("power"), "targets": {}}
    for t in TARGETS:
        r = f"reason_{t[len('target_'):]}"
        g = panel_lf.group_by(r).agg(pl.len()).collect()
        by_year = panel_lf.group_by("d_year").agg((pl.col(t) == 1).sum().alias("pos"), (pl.col(t) == 0).sum().alias("neg"),
                                                  pl.col(t).null_count().alias("null")).sort("d_year").collect()
        reasons = {k: int(v) for k, v in g.iter_rows()}
        out["targets"][t] = {
            "positive": reasons.get("positive", 0),
            "negative": reasons.get("negative", 0) + reasons.get("negative_transient_only", 0),
            "null_reasons": {k: v for k, v in reasons.items() if k not in ("positive", "negative", "negative_transient_only")},
            "negative_transient_only": reasons.get("negative_transient_only", 0),
            "by_year": {str(y): {"pos": int(p), "neg": int(n), "null": int(nu)} for y, p, n, nu in by_year.iter_rows()},
        }
    return out


# ---------------------------------------------------------------------------
# 7. Поток по годам (для Kaggle): сырой журнал → части → панель
# ---------------------------------------------------------------------------
def read_journal(pl: Any, path: Path) -> Any:
    schema = {c: pl.String for c in EVENT_COLUMNS}
    return pl.read_csv(path, schema_overrides=schema, infer_schema_length=0, encoding="utf8-lossy",
                       columns=EVENT_COLUMNS).filter(pl.col("ид_события") != "ид_события")


def read_catalogue(pl: Any, path: Path) -> Any:
    cat = pl.read_csv(path, infer_schema_length=0, encoding="utf8-lossy")
    return cat.select([c for c in CATALOGUE_COLUMNS if c in cat.columns]).unique("ид_канала_данных", keep="last")


def process_year(pl: Any, raw: Any, tax: dict[str, Any], catalogue: Any, gas_carry: Any) -> dict[str, Any]:
    ev = classify_events(pl, raw, tax, catalogue)
    sec = second_table(pl, ev, tax)
    daily = daily_aggregates(pl, ev, sec, tax)
    gas_daily, gas_carry = gas_crossings(pl, ev, gas_carry, tax["numeric"]["gas_threshold_percent"])
    meta = ev.group_by("ch").agg(pl.col("тип_датчика").drop_nulls().last(), pl.col("тип_инж_системы").drop_nulls().last(),
                                 pl.col("ид_объект").drop_nulls().last())
    class_counts = {k: int(v) for k, v in ev.group_by("cls").len().iter_rows()}
    streams = tax["stream_mapping"]["streams"]
    mapped = {c for st in streams.values() for key in ("fault", "ok", "unknown") for c in st[key]}
    stream_audit = {}
    for name in streams:
        g = sec.group_by(f"{name}_cls", f"{name}_a_cause").len()
        stream_audit[name] = {f"{st or 'none'}{'_' + cause if cause else ''}": int(n) for st, cause, n in g.iter_rows()}
    stream_audit["events_in_no_stream_by_class"] = {k: v for k, v in class_counts.items() if k not in mapped}
    # «Неопределен»: сколько каналов и какие классы соседствуют (агрегаты, порядок внутри секунды не используется)
    evs = ev.select("ch", "t", "cls").sort("ch", "t")
    evs = evs.with_columns(pl.col("cls").shift(1).over("ch").alias("prev"), pl.col("cls").shift(-1).over("ch").alias("next"))
    svc = evs.filter(pl.col("cls") == "service")
    service_audit = {"events": svc.height, "channels": svc["ch"].n_unique(),
                     "prev_class": {str(k): int(v) for k, v in svc.group_by("prev").len().sort("len", descending=True).head(10).iter_rows()},
                     "next_class": {str(k): int(v) for k, v in svc.group_by("next").len().sort("len", descending=True).head(10).iter_rows()}}
    unknown_values = {k: int(v) for k, v in ev.filter(pl.col("cls") == "unknown_value").group_by("v").len()
                      .sort("len", descending=True).head(30).iter_rows()}
    return {
        "daily": daily, "link_cp": change_points(pl, sec, "link_cls"), "power_cp": change_points(pl, sec, "power_cls"),
        "gas_daily": gas_daily, "gas_carry": gas_carry, "meta": meta, "t_max": ev["t"].max(),
        "audit": {"events": ev.height, "channels": ev["ch"].n_unique(), "seconds": sec.height,
                  "multi_value_seconds": int((sec["n_values"] > 1).sum()),
                  "link_fault_seconds": int((sec["link_cls"] == "F").sum()),
                  "link_fault_seconds_with_other_value": int(((sec["has_fault"]) & (sec["n_values"] > 1)).sum()),
                  "link_ambiguous_seconds": int((sec["link_cls"] == "A").sum()),
                  "class_counts": class_counts, "unknown_values_top30": unknown_values,
                  "stream_mapping": stream_audit, "service_value": service_audit},
    }


def empty_gas_carry(pl: Any) -> Any:
    return pl.DataFrame(schema={"ch": pl.String, "t": pl.Datetime("us"), "mn": pl.Float64, "mx": pl.Float64})


def journal_max_time(pl: Any, path: Path) -> datetime:
    """Лёгкий предпроход: последний момент в файле (для общей границы данных)."""
    t = pl.concat_str(["дата", "время"], separator=" ").str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S", strict=False)
    return _scan_source(pl, path).select(t.max()).collect().item()


def _scan_source(pl: Any, path: Path) -> Any:
    path = Path(path)
    if path.suffix == ".parquet":
        return pl.scan_parquet(path)
    schema = {c: pl.String for c in EVENT_COLUMNS}
    return pl.scan_csv(path, schema_overrides=schema, infer_schema_length=0, encoding="utf8-lossy")


def scan_bucket(pl: Any, path: Path, bucket: int, n_buckets: int, channel_filter: Any = None) -> Any:
    lf = _scan_source(pl, path).select(EVENT_COLUMNS).filter(pl.col("ид_события") != "ид_события")
    if n_buckets > 1:
        lf = lf.filter(pl.col("ид_канала_данных").hash(seed=20260923) % n_buckets == bucket)
    if channel_filter is not None:
        lf = lf.filter(channel_filter)
    return lf.collect()


def _merge_audits(parts: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for a in parts:
        for k, v in a.items():
            if isinstance(v, bool) or v is None:
                out.setdefault(k, v)
            elif isinstance(v, (int, float)):
                out[k] = out.get(k, 0) + v
            elif isinstance(v, dict):
                out[k] = _merge_audits([out.get(k, {}), v])
            else:
                out.setdefault(k, v)
    return out


def build_event_panel(pl: Any, journal_paths: list[Path], catalogue_path: Path, taxonomy_path: Path,
                      config: dict[str, Any] | None = None, log: Any = print, n_buckets: int = 1,
                      out_dir: Path | None = None, channel_filter: Any = None,
                      data_end: datetime | None = None) -> tuple[Any, dict[str, Any]]:
    """Собирает панель по группам каналов (каналы независимы). При out_dir пишет части parquet и
    возвращает (None, audit); иначе возвращает панель в памяти."""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    tax = load_taxonomy(taxonomy_path)
    cfg["gas_threshold_percent"] = tax["numeric"]["gas_threshold_percent"]
    if not cfg["service_as_unknown"]:
        link = tax["stream_mapping"]["streams"]["link"]
        link["unknown"] = [c for c in link["unknown"] if c != "service"]
    if cfg["power_ok_from_function"]:
        power = tax["stream_mapping"]["streams"]["power"]
        power["ok"] = list(dict.fromkeys(power["ok"] + ["normal", "event_alarm", "numeric"]))
    cfg["stream_mapping_version"] = tax["stream_mapping"]["version"]
    catalogue = read_catalogue(pl, catalogue_path)
    # data_end задаётся явно на runtime (конец дня D): события после D в сборку не попадают (см. channel_filter)
    t_max = data_end if data_end is not None else max(journal_max_time(pl, p) for p in journal_paths)
    panels, part_paths, per_file_parts, ep_parts = [], [], [], []
    for b in range(n_buckets):
        carry = empty_gas_carry(pl)
        parts: dict[str, list[Any]] = {"daily": [], "link_cp": [], "power_cp": [], "gas_daily": [], "meta": []}
        per_file = {}
        for path in journal_paths:
            raw = scan_bucket(pl, Path(path), b, n_buckets, channel_filter)
            if raw.is_empty():
                continue
            res = process_year(pl, raw, tax, catalogue, carry)
            carry = res["gas_carry"]
            for k in parts:
                parts[k].append(res[k])
            per_file[Path(path).name] = res["audit"]
            del raw, res
        if not parts["daily"]:
            continue
        daily = pl.concat(parts["daily"], how="vertical_relaxed")
        dup = daily.height - daily.select("ch", "day").unique().height
        if dup:
            raise ValueError(f"дневные агрегаты пересекаются между файлами: {dup} строк")
        link_cp = rle(pl, pl.concat(parts["link_cp"], how="vertical"))
        power_cp = rle(pl, pl.concat(parts["power_cp"], how="vertical"))
        gas_daily = pl.concat(parts["gas_daily"], how="vertical").group_by("ch", "day").agg(pl.all().sum())
        meta = pl.concat(parts["meta"], how="vertical_relaxed").group_by("ch").agg(pl.all().drop_nulls().last())
        panel, audit = build_panel_from_parts(pl, daily, link_cp, power_cp, gas_daily, meta, t_max, cfg)
        per_file_parts.append({"per_file": per_file})
        ep_parts.append(audit.pop("_episode_durations"))
        if out_dir is not None:
            path = Path(out_dir) / f"event_panel_v3_part{b:02d}.parquet"
            panel.write_parquet(path, compression="zstd")
            part_paths.append(path)
            del panel
        else:
            panels.append(panel)
        log(f"группа каналов {b + 1}/{n_buckets}: строк {audit['rows']:,}, каналов {audit['channels']:,}")
    if out_dir is not None:
        full = pl.scan_parquet(part_paths)
    else:
        full = pl.concat(panels, how="vertical_relaxed").lazy()
    audit = final_audit(pl, full, pl.concat(ep_parts, how="vertical"))
    audit["feature_columns"] = [c for c in full.collect_schema().names() if c.startswith("f_")] + BASE_FEATURES
    audit["target_columns"] = TARGETS
    audit.update({"schema_version": SCHEMA_VERSION, "config": cfg, "taxonomy_version": tax["version"],
                  "taxonomy_sha256": tax["_sha256"], "data_end": str(t_max), "n_buckets": n_buckets,
                  "per_file": _merge_audits(per_file_parts)["per_file"] if per_file_parts else {},
                  "part_files": [p.name for p in part_paths]})
    return (None if out_dir is not None else full.collect()), audit


def csv_to_parquet(pl: Any, csv_path: Path, out_path: Path) -> dict[str, Any]:
    """Сырой CSV → parquet только нужных колонок (все строки как строки, без интерпретации)."""
    schema = {c: pl.String for c in EVENT_COLUMNS}
    lf = pl.scan_csv(csv_path, schema_overrides=schema, infer_schema_length=0, encoding="utf8-lossy").select(EVENT_COLUMNS)
    lf.sink_parquet(out_path, compression="zstd")
    rows = pl.scan_parquet(out_path).select(pl.len()).collect().item()
    return {"rows": int(rows), "parquet_bytes": Path(out_path).stat().st_size}


# ---------------------------------------------------------------------------
# 8. Самопроверки на синтетике (для notebook)
# ---------------------------------------------------------------------------
def run_event_panel_self_tests(taxonomy_path: Path, work_dir: Path) -> dict[str, bool]:
    import polars as pl
    import random

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    t0 = datetime(2024, 3, 1)

    def events(rows):
        return pl.DataFrame({"ид_события": [str(i) for i in range(len(rows))],
                             "ид_канала_данных": [r[0] for r in rows],
                             "дата": [r[1].strftime("%Y-%m-%d") for r in rows],
                             "время": [r[1].strftime("%H:%M:%S") for r in rows],
                             "тревожное": ["f"] * len(rows), "значение_датчика": [r[2] for r in rows]})

    def catalogue(chs, typ="Состояние насоса"):
        return pl.DataFrame({"ид_канала_данных": chs, "тип_инж_системы": ["x"] * len(chs),
                             "тип_датчика": [typ] * len(chs), "ид_объект": ["1"] * len(chs)})

    def build(name, rows, chs, **kw):
        d = work_dir / name
        d.mkdir(exist_ok=True)
        events(rows).write_csv(d / "j.csv")
        catalogue(chs).write_csv(d / "c.csv")
        return build_event_panel(pl, [d / "j.csv"], d / "c.csv", taxonomy_path, log=lambda *a: None, **kw)

    def row(panel, ch, day):
        r = panel.filter((pl.col("d_channel_key") == pseudo_key(ch)) & (pl.col("d_cutoff_date") == (t0 + timedelta(days=day)).date()))
        return r.row(0, named=True)

    report: dict[str, bool] = {}
    hb = [("A", t0 + timedelta(days=d, hours=12), "Норма") for d in range(12)]
    p, _ = build("onset", hb + [("A", t0 + timedelta(days=5, hours=13), "Неисправен"), ("A", t0 + timedelta(days=5, hours=14), "Норма")], ["A"])
    report["strict_onset_in_window_is_positive"] = row(p, "A", 3)["target_t2a_link_onset"] == 1
    report["onset_in_d1_is_competing_not_filtered"] = row(p, "A", 4)["target_t2a_link_onset"] == 0 and row(p, "A", 4)["competing_link_onset_d1"]
    t = t0 + timedelta(days=5, hours=13)
    p, _ = build("amb", hb + [("A", t, "Неисправен"), ("A", t, "Норма")], ["A"])
    r = row(p, "A", 3)  # конфликт в одной секунде → не onset и не 0, а null(ambiguous_onset)
    report["same_second_conflict_is_null"] = r["target_t2a_link_onset"] is None and r["reason_t2a_link_onset"] == "ambiguous_onset"
    rnd = random.Random(1)
    vals = ["Норма", "Неисправен", "Обесточен", "Есть питание", "Выключен", "Неопределен", "0,05", "1,3", "-127"]
    rows = [(f"C{c}", t0 + timedelta(days=d, seconds=rnd.randint(0, 86399)), rnd.choice(vals))
            for c in range(8) for d in range(30) for _ in range(rnd.randint(0, 5))]
    chs = [f"C{c}" for c in range(8)]
    base, _ = build("rand1", rows, chs)
    out = work_dir / "rand_parts"
    out.mkdir(exist_ok=True)
    build("rand2", rows, chs, n_buckets=3, out_dir=out)
    parts = pl.read_parquet(sorted(out.glob("*.parquet")))
    key = ["d_channel_key", "d_cutoff_date"]
    report["channel_buckets_do_not_change_panel"] = base.sort(key).equals(parts.sort(key))
    report["no_raw_identifiers_in_panel"] = not any(c in base.write_csv() for c in ("C1,", "C2,"))
    return report


def label_changes(pl: Any, main: Any, variant: Any, targets: list[str] | None = None) -> dict[str, dict[str, int]]:
    """Сколько меток меняется между основной и sensitivity-версией (только агрегаты, по ключу строки)."""
    k = ["d_channel_key", "d_cutoff_date"]
    out: dict[str, dict[str, int]] = {}
    for t in targets or TARGETS:
        j = main.select(k + [t]).join(variant.select(k + [t]), on=k, how="full", suffix="_v", coalesce=True)
        a = pl.col(t).cast(pl.String).fill_null("null")
        b = pl.col(f"{t}_v").cast(pl.String).fill_null("null")
        g = j.with_columns(a.alias("a"), b.alias("b")).filter(pl.col("a") != pl.col("b")).group_by("a", "b").len()
        out[t] = {f"{x}->{y}": int(n) for x, y, n in g.sort("a", "b").iter_rows()}
    return out
