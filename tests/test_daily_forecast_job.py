"""Daily ML handoff: conservative advice and immutable, retry-safe journal."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "ml" / "sensor_failure"))

import daily_forecast_job as job  # noqa: E402
import lct_ml_runtime as runtime  # noqa: E402


def test_recommendations_never_turn_proxy_or_stub_into_automatic_action() -> None:
    gas = {"decision_status": "experimental_shadow", "score": 0.99,
           "maintenance_context": "possible_recent_silence", "reason_codes": []}
    advice = runtime.gas_recommendation(gas)
    assert advice["code"] == "CHECK_MAINTENANCE_LOG"
    assert advice["automated_action_allowed"] is False
    assert "не подтверждает" in advice["text_ru"]
    current = runtime.gas_recommendation({"decision_status": "abstain", "score": None,
                                          "reason_codes": ["ABOVE_THRESHOLD_AT_D"]})
    assert current["code"] == "CURRENT_ALARM_PROTOCOL"
    assert "Прогноз здесь неприменим" in current["text_ru"]
    demo = runtime.incident_recommendation({"label_source": "stub", "evidence_level": "E4",
                                            "decision_status": "baseline_only", "score": 0.9})
    assert demo["code"] == "DEMO_ONLY" and not demo["automated_action_allowed"]
    missing = runtime.incident_recommendation({"label_source": "stub", "abstain_reason": "INSUFFICIENT_LABELS"})
    assert missing["code"] == "NO_INCIDENT_FORECAST" and "INSUFFICIENT_LABELS" in missing["basis_codes"]


def test_score_day_adds_recommendations_without_changing_scores(tmp_path: Path) -> None:
    gas_predictor = SimpleNamespace(
        build_features=lambda *_: {},
        predict=lambda *_: [{"ид_канала_данных": "C1", "score": 0.42,
                             "decision_status": "experimental_shadow", "reason_codes": []}])
    incident_predictor = SimpleNamespace(
        predict=lambda *_args, **_kwargs: [{"ид_объект": "O1", "score": 0.8,
                                             "label_source": "stub", "evidence_level": "E4",
                                             "decision_status": "baseline_only", "abstain_reason": None}])
    bundles = [SimpleNamespace(kind="gas", name="gas-v3", module=gas_predictor, bundle={}, info={}),
               SimpleNamespace(kind="incident", name="incident-demo", module=incident_predictor,
                               bundle={"spec": {"label_source": "stub"}}, info={})]
    catalogue = pl.DataFrame({"ид_канала_данных": ["C1"], "ид_объект": ["O1"]})
    panel = pl.DataFrame({"d_cutoff_date": [date(2025, 1, 1)], "d_object_key": ["O1"]})
    ep = SimpleNamespace(read_catalogue=lambda *_: catalogue, pseudo_key=lambda value: value)
    scored = runtime.MLRuntime.__new__(runtime.MLRuntime)
    scored.bundles, scored.primary_gas = bundles, "gas-v3"
    scored._context_panel = lambda *_: (panel, ep)
    scored.maintenance_context = lambda *_: {}
    out = scored.score_day([tmp_path / "journal.csv"], tmp_path / "catalogue.csv",
                           date(2025, 1, 1), request_id="r1")
    assert out["gas"][0]["score"] == 0.42
    assert out["gas"][0]["recommendation"]["code"] == "REVIEW_GAS_TREND"
    assert out["incidents"][0]["score"] == 0.8
    assert out["incidents"][0]["recommendation"]["code"] == "DEMO_ONLY"


def test_daily_job_writes_once_and_requires_revision_when_inputs_change(tmp_path: Path) -> None:
    journal, catalogue = tmp_path / "journal.csv", tmp_path / "catalogue.csv"
    journal.write_text("synthetic", encoding="utf-8")
    catalogue.write_text("synthetic", encoding="utf-8")
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    (bundles / "gas.zip").write_bytes(b"synthetic")
    marker = tmp_path / "ready.txt"
    marker.write_text("2025-01-01", encoding="utf-8")
    calls = []

    class FakeRuntime:
        def __init__(self, path: Path):
            assert path == bundles

        def score_day(self, files, cat, day, request_id, ppr_windows, recent_incidents):
            calls.append(request_id)
            assert files == [journal] and cat == catalogue and day == date(2025, 1, 1)
            return {"as_of_date": day.isoformat(), "request_id": request_id,
                    "gas": [{"ид_канала_данных": "secret-channel", "score": 0.4,
                             "recommendation": runtime.gas_recommendation({"decision_status": "experimental_shadow"})}],
                    "incidents": []}

    params = ([journal], catalogue, bundles, tmp_path / "journal_out")
    first = job.run_daily(*params, "2025-01-01", ready_marker=marker, runtime_factory=FakeRuntime)
    assert first["status"] == "written" and first["gas_count"] == 1
    saved = json.loads(Path(first["path"]).read_text(encoding="utf-8"))
    assert saved["forecast"]["gas"][0]["ид_канала_данных"] == "secret-channel"
    again = job.run_daily(*params, "2025-01-01", ready_marker=marker, runtime_factory=FakeRuntime)
    assert again["status"] == "already_written" and len(calls) == 1
    journal.write_text("synthetic changed", encoding="utf-8")
    with pytest.raises(ValueError, match="new revision"):
        job.run_daily(*params, "2025-01-01", ready_marker=marker, runtime_factory=FakeRuntime)
    revised = job.run_daily(*params, "2025-01-01", revision=2, ready_marker=marker,
                            runtime_factory=FakeRuntime)
    assert revised["status"] == "written" and len(calls) == 2
    assert Path(first["path"]).exists() and Path(revised["path"]).exists()


def test_daily_job_waits_for_ready_data_and_does_not_publish_failure(tmp_path: Path) -> None:
    source = tmp_path / "journal.csv"
    source.write_text("synthetic", encoding="utf-8")
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    (bundles / "gas.zip").write_bytes(b"synthetic")
    marker = tmp_path / "ready.txt"
    marker.write_text("2025-01-02", encoding="utf-8")
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="ready marker"):
        job.run_daily([source], source, bundles, out, "2025-01-01", ready_marker=marker)

    marker.write_text("2025-01-01", encoding="utf-8")

    class FailedRuntime:
        def __init__(self, _: Path):
            pass

        def score_day(self, *_args, **_kwargs):
            raise RuntimeError("synthetic scoring failure")

    with pytest.raises(RuntimeError, match="synthetic scoring failure"):
        job.run_daily([source], source, bundles, out, "2025-01-01", ready_marker=marker,
                      runtime_factory=FailedRuntime)
    assert not list(out.glob("*.json")) and not list(out.glob("*.lock"))

    class ChangingRuntime:
        def __init__(self, _: Path):
            pass

        def score_day(self, *_args, **kwargs):
            source.write_text("synthetic changed during scoring", encoding="utf-8")
            return {"as_of_date": "2025-01-01", "request_id": kwargs["request_id"],
                    "gas": [{"recommendation": runtime.gas_recommendation({"decision_status": "abstain"})}],
                    "incidents": []}

    with pytest.raises(RuntimeError, match="changed while scoring"):
        job.run_daily([source], source, bundles, out, "2025-01-01", ready_marker=marker,
                      runtime_factory=ChangingRuntime)
    assert not list(out.glob("*.json")) and not list(out.glob("*.lock"))


def test_stale_lock_requires_explicit_recovery_and_age_threshold(tmp_path: Path) -> None:
    source = tmp_path / "journal.csv"
    source.write_text("synthetic", encoding="utf-8")
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    (bundles / "gas.zip").write_bytes(b"synthetic")
    out = tmp_path / "out"
    out.mkdir()
    lock = out / "forecast_2025-01-01_r1.lock"
    lock.write_text('{"pid": 1, "host": "old-host"}', encoding="utf-8")
    params = ([source], source, bundles, out, "2025-01-01")

    with pytest.raises(RuntimeError, match="age .* h"):
        job.run_daily(*params)
    with pytest.raises(RuntimeError, match="verify the previous job"):
        job.run_daily(*params, break_stale_lock_hours=2)
    assert lock.exists()

    old = time.time() - 3 * 3600
    os.utime(lock, (old, old))

    class FakeRuntime:
        def __init__(self, _: Path):
            pass

        def score_day(self, *_args, **kwargs):
            return {"as_of_date": "2025-01-01", "request_id": kwargs["request_id"],
                    "gas": [{"recommendation": {"code": "REVIEW_GAS_TREND"}}], "incidents": []}

    result = job.run_daily(*params, break_stale_lock_hours=2, runtime_factory=FakeRuntime)
    assert result["status"] == "written"
    assert not lock.exists()
