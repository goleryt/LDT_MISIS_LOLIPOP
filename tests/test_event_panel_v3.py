"""Contracts for the event-level panel v3 state machine (spec: Drive docs 05→12, docs/EVENT_PANEL_V3_RU.md).

Все потоки синтетические. Независимые тест-кейсы GPT добавляются отдельным файлом без правок реализации под них.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

import polars as pl
import pytest

ROOT = Path(__file__).parents[1]
MODULE_DIR = ROOT / "ml" / "sensor_failure"
sys.path.insert(0, str(MODULE_DIR))

import event_panel_v3 as ep  # noqa: E402

TAX = MODULE_DIR / "config" / "state_taxonomy_v3.json"
T0 = datetime(2024, 3, 1)


def _events(rows: list[tuple[str, datetime, str]]) -> pl.DataFrame:
    return pl.DataFrame({
        "ид_события": [str(i) for i in range(len(rows))],
        "ид_канала_данных": [r[0] for r in rows],
        "дата": [r[1].strftime("%Y-%m-%d") for r in rows],
        "время": [r[1].strftime("%H:%M:%S") for r in rows],
        "тревожное": ["f"] * len(rows),
        "значение_датчика": [r[2] for r in rows],
    })


def _catalogue(types: dict[str, str]) -> pl.DataFrame:
    return pl.DataFrame({"ид_канала_данных": list(types), "тип_инж_системы": ["x"] * len(types),
                         "тип_датчика": list(types.values()), "ид_объект": ["1"] * len(types)})


def _build(tmp_path: Path, rows, types, config=None):
    j = tmp_path / "j.csv"
    c = tmp_path / "c.csv"
    _events(rows).write_csv(j)
    _catalogue(types).write_csv(c)
    return ep.build_event_panel(pl, [j], c, TAX, config=config, log=lambda *a: None)


def _heartbeat(ch: str, days: int, value: str = "Норма", hour: int = 12) -> list:
    return [(ch, T0 + timedelta(days=d, hours=hour), value) for d in range(days)]


def _row(panel: pl.DataFrame, ch: str, day: int) -> dict:
    key = ep.pseudo_key(ch)
    d = (T0 + timedelta(days=day)).date()
    r = panel.filter((pl.col("d_channel_key") == key) & (pl.col("d_cutoff_date") == d))
    assert r.height == 1, (ch, day, r.height)
    return r.row(0, named=True)


def test_taxonomy_has_no_duplicate_classes() -> None:
    tax = ep.load_taxonomy(TAX)
    assert tax["_value_to_class"]["Неисправен"] == "link_fault"
    assert tax["_value_to_class"]["Обесточен"] == "power_off"


def test_strict_onset_in_d2_is_positive_and_d1_is_competing(tmp_path) -> None:
    rows = _heartbeat("A", 12)
    rows += [("A", T0 + timedelta(days=5, hours=13), "Неисправен"), ("A", T0 + timedelta(days=5, hours=14), "Норма")]
    panel, _ = _build(tmp_path, rows, {"A": "Состояние насоса"})
    d3 = _row(panel, "A", 3)  # окно D+2 = день 5
    assert d3["target_t2a_link_onset"] == 1
    d4 = _row(panel, "A", 4)  # onset в D+1 = день 5: не фильтруется, а 0 + competing
    assert d4["target_t2a_link_onset"] == 0 and d4["competing_link_onset_d1"]
    # onset длился 1 ч ≥ τ = 5 мин → sustained
    assert d3["target_t2b_link_sustained"] == 1


def test_short_episode_is_transient_for_sustained_target(tmp_path) -> None:
    rows = _heartbeat("A", 12)
    rows += [("A", T0 + timedelta(days=5, hours=13), "Неисправен"), ("A", T0 + timedelta(days=5, hours=13, seconds=20), "Норма")]
    panel, _ = _build(tmp_path, rows, {"A": "Состояние насоса"})
    d3 = _row(panel, "A", 3)
    assert d3["target_t2a_link_onset"] == 1
    assert d3["target_t2b_link_sustained"] == 0
    assert d3["reason_t2b_link_sustained"] == "negative_transient_only"


def test_same_second_fault_and_normal_is_ambiguous_not_onset(tmp_path) -> None:
    rows = _heartbeat("A", 12)
    t = T0 + timedelta(days=5, hours=13)
    rows += [("A", t, "Неисправен"), ("A", t, "Норма")]
    panel, audit = _build(tmp_path, rows, {"A": "Состояние насоса"})
    d3 = _row(panel, "A", 3)
    # A-секунда могла скрыть переход: не 1 и не 0, а null(ambiguous_onset) (GPT 14, C2)
    assert d3["target_t2a_link_onset"] is None and d3["reason_t2a_link_onset"] == "ambiguous_onset"
    assert audit["per_file"]["j.csv"]["link_ambiguous_seconds"] == 1


def test_fault_with_power_off_in_same_second_is_fault(tmp_path) -> None:
    # stream mapping v1: питание знает только явные «Есть питание»/«Обесточен», поэтому история питания задаётся явно
    rows = _heartbeat("A", 12) + _heartbeat("A", 12, value="Есть питание", hour=11)
    t = T0 + timedelta(days=5, hours=13)
    rows += [("A", t, "Неисправен"), ("A", t, "Обесточен"), ("A", t + timedelta(hours=2), "Норма")]
    panel, _ = _build(tmp_path, rows, {"A": "Состояние насоса"})
    d3 = _row(panel, "A", 3)
    assert d3["target_t2a_link_onset"] == 1
    assert d3["target_t2c_power_onset"] == 1


def test_open_episode_at_d_is_not_eligible(tmp_path) -> None:
    rows = _heartbeat("A", 3) + [("A", T0 + timedelta(days=3, hours=13), "Неисправен")]
    rows += [("A", T0 + timedelta(days=d, hours=12), "Неисправен") for d in range(4, 8)]
    rows += [("A", T0 + timedelta(days=8, hours=12), "Норма")]
    panel, _ = _build(tmp_path, rows, {"A": "Состояние насоса"})
    r = _row(panel, "A", 4)
    assert r["target_t2a_link_onset"] is None and r["reason_t2a_link_onset"] == "state_not_ok_at_D"


def test_first_fault_without_history_is_ambiguous(tmp_path) -> None:
    rows = [("A", T0 + timedelta(days=2, hours=1), "Неисправен"), ("A", T0 + timedelta(days=2, hours=3), "Норма")]
    rows += _heartbeat("A", 12)[3:]
    panel, audit = _build(tmp_path, rows, {"A": "Состояние насоса"})
    assert audit["link_episodes"]["ambiguous_onsets"] == 1 and audit["link_episodes"]["strict_onsets"] == 0


def test_censoring_at_data_end_gives_null_for_sustained(tmp_path) -> None:
    rows = _heartbeat("A", 6) + [("A", T0 + timedelta(days=5, hours=23, minutes=58), "Неисправен")]
    # данные кончаются через 1 минуту после старта: τ = 5 мин недостижимо
    rows += [("B", T0 + timedelta(days=5, hours=23, minutes=59), "Норма")]
    _, audit = _build(tmp_path, rows, {"A": "Состояние насоса", "B": "КД Дверь"})
    assert audit["link_episodes"]["strict_censored"] == 1 and audit["link_episodes"]["sustained_null"] == 1


def test_silent_window_is_unobserved_not_negative(tmp_path) -> None:
    rows = _heartbeat("A", 3) + [("A", T0 + timedelta(days=9, hours=12), "Норма")]
    rows += _heartbeat("B", 12)  # чтобы данные тянулись дальше окна
    panel, _ = _build(tmp_path, rows, {"A": "Состояние насоса", "B": "КД Дверь"})
    r = _row(panel, "A", 2)  # окно D+2 = день 4, D+3 = день 5 — событий нет
    assert r["target_t2a_link_onset"] is None and r["reason_t2a_link_onset"] == "unobserved_window"


def test_features_do_not_depend_on_future(tmp_path) -> None:
    base = _heartbeat("A", 20)
    extra = [("A", T0 + timedelta(days=15, hours=h), "Неисправен") for h in (1, 2)] + \
            [("A", T0 + timedelta(days=15, hours=5), "Норма")]
    p1, _ = _build(tmp_path / "a", base, {"A": "Состояние насоса"}) if (tmp_path / "a").mkdir() is None else (None, None)
    p2, _ = _build(tmp_path / "b", base + extra, {"A": "Состояние насоса"}) if (tmp_path / "b").mkdir() is None else (None, None)
    feats = [c for c in p1.columns if c.startswith("f_") or c in ("link_state", "power_state", "n_events")]
    cut = (T0 + timedelta(days=14)).date()
    a = p1.filter(pl.col("d_cutoff_date") <= cut).select(feats)
    b = p2.filter(pl.col("d_cutoff_date") <= cut).select(feats)
    assert a.equals(b)


def test_gas_crossing_is_strict_and_threshold_state_blocks_eligibility(tmp_path) -> None:
    rows = [("G", T0 + timedelta(days=d, hours=h), "0,05") for d in range(12) for h in (0, 6, 12, 18)]
    rows += [("G", T0 + timedelta(days=5, hours=19), "1,20"), ("G", T0 + timedelta(days=5, hours=20), "1,40")]
    rows += [("G", T0 + timedelta(days=5, hours=21), "0,10")]
    panel, _ = _build(tmp_path, rows, {"G": "Газовый датчик"})
    assert _row(panel, "G", 3)["target_t4_gas_cross"] == 1  # одно строгое пересечение, 1,40 — продолжение
    assert _row(panel, "G", 6)["target_t4_gas_cross"] == 0


def test_date_like_values_are_split(tmp_path) -> None:
    t = T0 + timedelta(days=1, hours=10)
    rows = _heartbeat("A", 5) + [("A", t, "01.01.1970 03:00:00"), ("A", t, t.strftime("%d.%m.%Y %H:%M:%S")),
                                 ("A", t, "05.05.2020 01:02:03")]
    _, audit = _build(tmp_path, rows, {"A": "КД Дверь"})
    cc = audit["per_file"]["j.csv"]["class_counts"]
    assert cc["clock_1970"] == 1 and cc["dup_timestamp"] == 1 and cc["date_other"] == 1


def test_no_raw_identifiers_in_panel(tmp_path) -> None:
    panel, _ = _build(tmp_path, _heartbeat("RAWID123456", 10), {"RAWID123456": "КД Дверь"})
    text = panel.write_csv()
    assert "RAWID123456" not in text


def _random_rows(seed: int = 3, channels: int = 12, days: int = 40) -> list:
    import random

    rnd = random.Random(seed)
    values = ["Норма", "Неисправен", "Обесточен", "Есть питание", "Выключен", "Включен", "Неопределен", "-127", "0,05", "1,3"]
    rows = []
    for c in range(channels):
        ch = f"C{c:03d}"
        for d in range(days):
            for _ in range(rnd.randint(0, 6)):
                t = T0 + timedelta(days=d, seconds=rnd.randint(0, 86399))
                rows.append((ch, t, rnd.choice(values)))
                if rnd.random() < 0.05:  # конфликт в одну секунду
                    rows.append((ch, t, rnd.choice(values)))
    return rows


def test_buckets_and_file_split_do_not_change_panel(tmp_path) -> None:
    rows = _random_rows()
    types = {f"C{c:03d}": ("Газовый датчик" if c % 3 == 0 else "Состояние насоса") for c in range(12)}
    j = tmp_path / "all.csv"
    c = tmp_path / "c.csv"
    ev = _events(rows)
    ev.write_csv(j)
    _catalogue(types).write_csv(c)
    ev.filter(pl.col("дата") < "2024-03-20").write_csv(tmp_path / "a.csv")
    ev.filter(pl.col("дата") >= "2024-03-20").write_csv(tmp_path / "b.csv")
    base, _ = ep.build_event_panel(pl, [j], c, TAX, log=lambda *a: None)
    split, _ = ep.build_event_panel(pl, [tmp_path / "a.csv", tmp_path / "b.csv"], c, TAX, log=lambda *a: None)
    out = tmp_path / "parts"
    out.mkdir()
    ep.build_event_panel(pl, [j], c, TAX, n_buckets=3, out_dir=out, log=lambda *a: None)
    bucketed = pl.read_parquet(sorted(out.glob("*.parquet")))
    key = ["d_channel_key", "d_cutoff_date"]
    assert base.sort(key).equals(split.sort(key))
    assert base.sort(key).equals(bucketed.sort(key))


def test_power_stream_ignores_other_signals(tmp_path) -> None:
    """Без явных сообщений о питании состояние питания неизвестно — «Норма» не делает питание O (GPT 16/Q2)."""
    rows = _heartbeat("A", 12) + [("A", T0 + timedelta(days=5, hours=13), "Обесточен")]
    panel, _ = _build(tmp_path, rows, {"A": "Состояние насоса"})
    d3 = _row(panel, "A", 3)
    assert d3["target_t2c_power_onset"] is None and d3["reason_t2c_power_onset"] == "no_state_history"


def test_service_value_sensitivity_switch(tmp_path) -> None:
    rows = _heartbeat("A", 12) + [("A", T0 + timedelta(days=4, hours=9), "Неопределен"),
                                  ("A", T0 + timedelta(days=5, hours=13), "Неисправен"),
                                  ("A", T0 + timedelta(days=5, hours=14), "Норма")]
    main, _ = _build(tmp_path, rows, {"A": "Состояние насоса"})
    (tmp_path / "s").mkdir()
    neutral, _ = _build(tmp_path / "s", rows, {"A": "Состояние насоса"}, config={"service_as_unknown": False})
    # основная версия: U в D+1 закрывается «Нормой» D+1 12:00 → onset в D+2 снова strict; разница видна в D+1 окне
    assert _row(neutral, "A", 3)["target_t2a_link_onset"] == 1
    assert _row(main, "A", 2)["reason_t2a_link_onset"] == "ambiguous_onset"   # окно D+2 = день 4 содержит U
    assert _row(neutral, "A", 2)["target_t2a_link_onset"] == 0


def test_gas_out_of_range_never_creates_threshold_crossing(tmp_path) -> None:
    """GPT 20: значения газа вне 0–100 % и технические коды не участвуют в пересечении 1 % и не рвут цепочку."""
    rows = [("G", T0 + timedelta(days=d, hours=h), "0,05") for d in range(12) for h in (0, 12)]
    rows += [("G", T0 + timedelta(days=5, hours=13), "327,68"),   # технический код
             ("G", T0 + timedelta(days=5, hours=14), "150"),      # > 100 %
             ("G", T0 + timedelta(days=5, hours=15), "-5")]       # < 0 %
    panel, audit = _build(tmp_path, rows, {"G": "Газовый датчик"})
    assert _row(panel, "G", 3)["target_t4_gas_cross"] == 0
    cc = audit["per_file"]["j.csv"]["class_counts"]
    assert cc.get("gas_out_of_range", 0) == 2 and cc.get("tech_value", 0) == 1
    (tmp_path / "b").mkdir()
    rows2 = rows + [("G", T0 + timedelta(days=5, hours=16), "1,2")]   # предыдущее валидное 0,05 → одно строгое пересечение
    panel2, _ = _build(tmp_path / "b", rows2, {"G": "Газовый датчик"})
    assert _row(panel2, "G", 3)["target_t4_gas_cross"] == 1


def test_same_second_values_across_threshold_are_not_a_strict_crossing(tmp_path) -> None:
    """GPT 37: 0 и 2,55 в одну секунду — порядок неизвестен, это не strict crossing, а неоднозначный исход."""
    rows = [("G", T0 + timedelta(days=d, hours=h), "0,05") for d in range(8) for h in (0, 6, 12, 18)]
    t = T0 + timedelta(days=5, hours=19)
    rows += [("G", t, "0,00"), ("G", t, "2,55")]
    panel, _ = _build(tmp_path, rows, {"G": "Газовый датчик"})
    r = _row(panel, "G", 3)
    assert r["target_t4_gas_cross"] is None and r["reason_t4_gas_cross"] == "unknown_previous_reading"


def test_clean_same_second_high_values_after_low_second_are_strict(tmp_path) -> None:
    rows = [("G", T0 + timedelta(days=d, hours=h), "0,05") for d in range(8) for h in (0, 6, 12, 18)]
    t = T0 + timedelta(days=5, hours=19)
    rows += [("G", t, "1,20"), ("G", t, "1,40")]
    panel, _ = _build(tmp_path, rows, {"G": "Газовый датчик"})
    assert _row(panel, "G", 3)["target_t4_gas_cross"] == 1


def test_mixed_last_gas_second_makes_eligibility_unknown(tmp_path) -> None:
    """GPT 42: в последней секунде D значения 0,05 и 1,30 — сторона порога на конец D неизвестна → не eligible."""
    rows = [("G", T0 + timedelta(days=d, hours=h), "0,05") for d in range(8) for h in (0, 6, 12, 18)]
    t = T0 + timedelta(days=3, hours=23)
    rows += [("G", t, "0,05"), ("G", t, "1,30")]
    panel, _ = _build(tmp_path, rows, {"G": "Газовый датчик"})
    r = _row(panel, "G", 3)
    assert r["target_t4_gas_cross"] is None and r["reason_t4_gas_cross"] == "ambiguous_last_reading_at_D"
    assert _row(panel, "G", 4)["reason_t4_gas_cross"] != "ambiguous_last_reading_at_D"   # следующий день однозначен
