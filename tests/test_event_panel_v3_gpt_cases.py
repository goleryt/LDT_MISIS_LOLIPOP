"""Независимые кейсы GPT (Drive, документ 14: C1–C12) против event_panel_v3.

Ожидания — как их записал GPT. Реализацию под кейсы не подгоняли: первый прогон сохранён до правок; правки C2/C7/C12
приводят код к уже согласованным правилам (06/Q2 — конфликт секунды → null; 09–10 — длительность ≥ τ только при
однозначном закрытии). Кейсы, которые текущая реализация сознательно не закрывает, помечены xfail с причиной.
После stream mapping v1 (таксономия 3.1, GPT 16) C3/C8/C12 закрыты; xfail остаётся только C5 (другой estimand).
S = канал A. Все события синтетические.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

import polars as pl
import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "ml" / "sensor_failure"))
sys.path.insert(0, str(Path(__file__).parent))

import event_panel_v3 as ep  # noqa: E402
from test_event_panel_v3 import _catalogue, _events  # noqa: E402

TAX = ROOT / "ml" / "sensor_failure" / "config" / "state_taxonomy_v3.json"
T0 = datetime(2024, 3, 1)
D = 5
O, F, U = "Норма", "Неисправен", "Неопределен"


def at(day: int, h: int = 0, m: int = 0) -> datetime:
    return T0 + timedelta(days=day, hours=h, minutes=m)


def run(tmp_path: Path, rows: list) -> tuple[dict, dict]:
    rows = rows + [("B", at(d, 12), O) for d in range(D + 8)]  # другой канал держит границу данных
    _events(rows).write_csv(tmp_path / "j.csv")
    _catalogue({"A": "Состояние насоса", "B": "КД Дверь"}).write_csv(tmp_path / "c.csv")
    panel, audit = ep.build_event_panel(pl, [tmp_path / "j.csv"], tmp_path / "c.csv", TAX, log=lambda *a: None)
    r = panel.filter((pl.col("d_channel_key") == ep.pseudo_key("A")) & (pl.col("d_cutoff_date") == at(D).date()))
    return r.row(0, named=True), audit["link_episodes"]


HIST = [("A", at(D, 12), O)]


def test_c1_strict_onset_closed_after_tau_and_csv_order(tmp_path) -> None:
    rows = HIST + [("A", at(D + 2, 8), F), ("A", at(D + 2, 8, 10), O)]
    for variant, rr in (("a", rows), ("b", list(reversed(rows)))):
        (tmp_path / variant).mkdir()
        r, e = run(tmp_path / variant, rr)
        assert r["link_state"] == "O" and r["target_t2a_link_onset"] == 1 and r["target_t2b_link_sustained"] == 1
        assert e["strict_onsets"] == 1
        assert (r["d_label_decision_end"] - r["d_cutoff_date"]).days == 4


def test_c2_conflicting_second_is_null(tmp_path) -> None:
    r, _ = run(tmp_path, HIST + [("A", at(D + 2, 8), F), ("A", at(D + 2, 8), O), ("A", at(D + 2, 9), O)])
    assert r["target_t2a_link_onset"] is None and r["reason_t2a_link_onset"] == "ambiguous_onset"


def test_c3_conflict_before_fault_makes_onset_non_strict(tmp_path) -> None:
    r, _ = run(tmp_path, HIST + [("A", at(D + 1, 9), F), ("A", at(D + 1, 9), O), ("A", at(D + 2, 8), F), ("A", at(D + 2, 9), O)])
    assert r["target_t2a_link_onset"] is None


def test_c3_service_value_as_unknown(tmp_path) -> None:
    r, _ = run(tmp_path, HIST + [("A", at(D + 1, 9), U), ("A", at(D + 2, 8), F), ("A", at(D + 2, 9), O)])
    assert r["target_t2a_link_onset"] is None


def test_c4_silent_stream_is_unobserved_even_if_neighbour_active(tmp_path) -> None:
    r, _ = run(tmp_path, HIST)
    assert r["target_t2a_link_onset"] is None and r["reason_t2a_link_onset"] == "unobserved_window"


@pytest.mark.xfail(reason="выбран иной estimand: «любой strict onset в D+2 при eligible на D», competing_d1 — флаг; "
                          "GPT по умолчанию ждёт null для «первого onset»", strict=True)
def test_c5_onset_in_d1_then_again_in_d2(tmp_path) -> None:
    r, _ = run(tmp_path, HIST + [("A", at(D + 1, 8), F), ("A", at(D + 1, 9), O), ("A", at(D + 2, 8), F), ("A", at(D + 2, 9), O)])
    assert r["competing_link_onset_d1"]
    assert r["target_t2a_link_onset"] is None


def test_c5_competing_flag_and_eligibility_kept(tmp_path) -> None:
    r, _ = run(tmp_path, HIST + [("A", at(D + 1, 8), F), ("A", at(D + 1, 9), O), ("A", at(D + 2, 8), F), ("A", at(D + 2, 9), O)])
    assert r["link_state"] == "O" and r["competing_link_onset_d1"]


@pytest.mark.parametrize("minutes,expected,reason", [(3, 0, "negative_transient_only"), (6, 1, "positive")])
def test_c6_transient_vs_sustained(tmp_path, minutes, expected, reason) -> None:
    r, _ = run(tmp_path, HIST + [("A", at(D + 2, 8), F), ("A", at(D + 2, 8, minutes), O)])
    assert r["target_t2a_link_onset"] == 1
    assert r["target_t2b_link_sustained"] == expected and r["reason_t2b_link_sustained"] == reason


def test_c7_unclosed_episode_is_censored(tmp_path) -> None:
    r, _ = run(tmp_path, HIST + [("A", at(D + 2, 8), F)])
    assert r["target_t2a_link_onset"] == 1
    assert r["target_t2b_link_sustained"] is None and r["reason_t2b_link_sustained"] == "censored_duration"


def test_c8_other_channel_does_not_close_episode(tmp_path) -> None:
    r, _ = run(tmp_path, HIST + [("A", at(D + 2, 8), F), ("B", at(D + 2, 8, 1), O)])
    assert r["target_t2b_link_sustained"] is None


def test_c8_other_signal_same_channel_does_not_close(tmp_path) -> None:
    r, _ = run(tmp_path, HIST + [("A", at(D + 2, 8), F), ("A", at(D + 2, 8, 1), "Есть питание")])
    assert r["target_t2b_link_sustained"] is None


def test_c9_first_visible_fault_and_repeats_are_not_strict(tmp_path) -> None:
    r, e = run(tmp_path, [("A", at(d, 8), F) for d in (D - 2, D - 1, D, D + 2)])
    assert e["strict_onsets"] == 0 and e["episodes"] == 1
    assert r["target_t2a_link_onset"] is None


def test_c10_exact_duplicates_are_one_onset(tmp_path) -> None:
    r, e = run(tmp_path, HIST + [("A", at(D + 2, 8), F), ("A", at(D + 2, 8), F), ("A", at(D + 2, 9), O)])
    assert r["target_t2a_link_onset"] == 1 and e["strict_onsets"] == 1


def test_c12_fault_with_other_stream_signal_same_second_is_onset(tmp_path) -> None:
    # stream mapping v1: «Есть питание» — поток питания, не O связи → конфликта в потоке связи нет, T2a = 1 (GPT 16/Q2)
    r, _ = run(tmp_path, HIST + [("A", at(D + 2, 8), F), ("A", at(D + 2, 8), "Есть питание"), ("A", at(D + 2, 9), O)])
    assert r["target_t2a_link_onset"] == 1
