"""Contracts for notebook 14: Kaggle staging (7z/csv → calendar-year parquet) and generated notebook."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unicodedata

import polars as pl
import pytest

ROOT = Path(__file__).parents[1]
MODULE_DIR = ROOT / "ml" / "sensor_failure"
sys.path.insert(0, str(MODULE_DIR))
sys.path.insert(0, str(Path(__file__).parent))

import event_panel_v3 as ep  # noqa: E402
import event_panel_v3_kaggle as kg  # noqa: E402
from test_event_panel_v3 import _catalogue, _events, _random_rows  # noqa: E402

TAX = MODULE_DIR / "config" / "state_taxonomy_v3.json"


def _write_inputs(root: Path, use_7z: bool) -> tuple[pl.DataFrame, pl.DataFrame]:
    rows = _random_rows(seed=11, channels=10, days=60)
    # переносим старт в конец года, чтобы данные шли через границу 2019/2020
    shift = datetime(2019, 12, 1) - datetime(2024, 3, 1)
    rows = [(c, t + shift, v) for c, t, v in rows]
    ev = _events(rows)
    types = {f"C{c:03d}": ("Газовый датчик" if c % 3 == 0 else "Состояние насоса") for c in range(10)}
    cat = _catalogue(types)
    ds = root / "dataset"
    ds.mkdir(parents=True)
    y19 = ev.filter(pl.col("дата") < "2019-12-30")
    y20 = ev.filter(pl.col("дата") >= "2019-12-30")        # 2 суток 2019 лежат в файле 2020
    y20 = pl.concat([y20, y19.tail(5)])                     # точные дубли между файлами
    for year, frame in ((2019, y19), (2020, y20)):
        csv = ds / f"ext-journal-{year}.csv"
        frame.write_csv(csv)
        if use_7z:
            subprocess.run([shutil.which("7z"), "a", "-bd", str(ds / f"ext-journal-{year}.7z"), str(csv)],
                           check=True, stdout=subprocess.DEVNULL)
            csv.unlink()
    cat.write_csv(ds / unicodedata.normalize("NFD", kg.CATALOGUE_NAME))  # имя как после загрузки с macOS
    return ev, cat


@pytest.mark.parametrize("use_7z", [False, pytest.param(True, marks=pytest.mark.skipif(
    shutil.which("7z") is None, reason="нет 7z"))])
def test_run_matches_direct_build_and_writes_aggregates_only(tmp_path, monkeypatch, use_7z) -> None:
    ev, cat = _write_inputs(tmp_path / "in", use_7z)
    monkeypatch.setenv("LDT_KAGGLE_INPUT_DIR", str(tmp_path / "in"))
    monkeypatch.setenv("LDT_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("LDT_STAGE_DIR", str(tmp_path / "stage"))
    cfg = kg.make_config_v3("FULL", {"taxonomy_path": str(TAX), "n_buckets": 3})
    result = kg.run_event_panel_v3(cfg, log=lambda *a: None)
    assert result["status"] == "completed"

    out = tmp_path / "out"
    assert sorted(p.name for p in out.iterdir()) == ["audit_event_panel_v3.json", "event_panel_v3",
                                                     "summary_event_panel_v3_ru.md"]
    manifest = json.loads((out / "event_panel_v3" / "panel_manifest_v3.json").read_text(encoding="utf-8"))
    assert manifest["stage"]["years"]["2019"]["rows_from_other_year_files"] > 0
    assert manifest["stage"]["years"]["2019"]["exact_duplicate_rows_dropped"] == 5
    for part in manifest["parts"]:
        assert hashlib.sha256((out / "event_panel_v3" / part["file"]).read_bytes()).hexdigest() == part["sha256"]
    assert not (tmp_path / "stage").exists()
    audit = json.loads((out / "audit_event_panel_v3.json").read_text(encoding="utf-8"))
    assert set(audit["sensitivity"]) == {"service_neutral", "power_ok_from_function"}
    for sv in audit["sensitivity"].values():
        assert set(sv["label_changes"]) == set(ep.TARGETS)
    assert "stream_mapping" in next(iter(audit["per_file"].values()))

    # тот же результат, что прямая сборка по одному файлу без дублей
    (tmp_path / "direct").mkdir()
    ev.write_csv(tmp_path / "direct" / "all.csv")
    cat.write_csv(tmp_path / "direct" / "c.csv")
    direct, _ = ep.build_event_panel(pl, [tmp_path / "direct" / "all.csv"], tmp_path / "direct" / "c.csv", TAX,
                                     log=lambda *a: None)
    staged = pl.read_parquet(sorted((out / "event_panel_v3").glob("*.parquet")))
    key = ["d_channel_key", "d_cutoff_date"]
    assert direct.sort(key).equals(staged.sort(key))

    raw_ids = set(ev["ид_канала_данных"].unique().to_list())
    for p in [out / "audit_event_panel_v3.json", out / "summary_event_panel_v3_ru.md",
              out / "event_panel_v3" / "panel_manifest_v3.json"]:
        text = p.read_text(encoding="utf-8")
        assert not any(f'"{r}"' in text or f" {r} " in text for r in raw_ids), p.name
    assert not (set(staged.select(pl.col(pl.String)).unpivot()["value"].drop_nulls().to_list()) & raw_ids)


def test_smoke_filters_years_and_channels(tmp_path, monkeypatch) -> None:
    _write_inputs(tmp_path / "in", use_7z=False)
    monkeypatch.setenv("LDT_KAGGLE_INPUT_DIR", str(tmp_path / "in"))
    monkeypatch.setenv("LDT_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("LDT_STAGE_DIR", str(tmp_path / "stage"))
    cfg = kg.make_config_v3("SMOKE", {"taxonomy_path": str(TAX), "smoke_years": [2019], "smoke_channel_share": 2})
    result = kg.run_event_panel_v3(cfg, log=lambda *a: None)
    assert result["status"] == "completed_smoke_non_comparable"
    assert 0 < result["channels"] < 10
    summary = (tmp_path / "out" / "summary_event_panel_v3_ru.md").read_text(encoding="utf-8")
    assert "SMOKE" in summary


def test_missing_inputs_stop_cleanly(tmp_path, monkeypatch) -> None:
    (tmp_path / "in").mkdir()
    monkeypatch.setenv("LDT_KAGGLE_INPUT_DIR", str(tmp_path / "in"))
    monkeypatch.setenv("LDT_OUTPUT_DIR", str(tmp_path / "out"))
    result = kg.run_event_panel_v3(kg.make_config_v3("FULL", {"taxonomy_path": str(TAX)}), log=lambda *a: None)
    assert result["status"] == "stopped" and "ext-journal" in result["stop_reason"]


def test_notebook_self_tests_pass(tmp_path) -> None:
    """Самопроверки, которые notebook выполняет на Kaggle, должны проходить."""
    report = ep.run_event_panel_self_tests(TAX, tmp_path)
    assert all(report.values()), report


def test_generated_notebook_embeds_runtime_and_compiles() -> None:
    path = ROOT / "notebooks" / "kaggle" / "14_event_panel_v3_cpu.ipynb"
    notebook = json.loads(path.read_text(encoding="utf-8"))
    assert notebook["metadata"]["kaggle"]["accelerator"] == "none"
    source = "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
    import generate_event_panel_v3_notebook as gen

    assert (MODULE_DIR / "event_panel_v3.py").read_text(encoding="utf-8").strip() in source, "regenerate notebook"
    assert gen.embeddable((MODULE_DIR / "event_panel_v3_kaggle.py").read_text(encoding="utf-8")).strip() in source
    assert "from event_panel_v3 import" not in source
    namespace: dict = {}
    exec(next("".join(c["source"]) for c in notebook["cells"] if "TAXONOMY_JSON =" in "".join(c["source"]))
         .split("TAXONOMY_PATH =")[0], namespace)
    assert json.loads(namespace["TAXONOMY_JSON"]) == json.loads(TAX.read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        assert "id" in cell
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), str(path), "exec")


def test_kaggle_layout_folders_and_renamed_catalogue(tmp_path, monkeypatch) -> None:
    """Как в реальном датасете Kaggle: папки ext-journal-YYYY/ext-journal-YYYY.csv, справочник переименован в «__.csv»,
    одного года нет; плюс посторонний CSV, который нельзя принять ни за журнал, ни за справочник."""
    ev, cat = _write_inputs(tmp_path / "flat", use_7z=False)
    ds = tmp_path / "in" / "let-dataset"
    for year in (2019, 2020):
        (ds / f"ext-journal-{year}").mkdir(parents=True)
        (tmp_path / "flat" / "dataset" / f"ext-journal-{year}.csv").rename(ds / f"ext-journal-{year}" / f"ext-journal-{year}.csv")
    (ds / "ext-journal-2022").mkdir()
    ev.head(3).with_columns(pl.lit("2022-05-01").alias("дата")).write_csv(ds / "ext-journal-2022" / "data.csv")  # имя без года
    cat.write_csv(ds / "__.csv")
    pl.DataFrame({"a": [1], "b": [2]}).write_csv(ds / "other.csv")
    src = kg.discover_sources(tmp_path / "in")
    assert sorted(src["journals"]) == [2019, 2020, 2022]
    assert src["journals"][2022].name == "data.csv"          # распознан по заголовку, год — из папки
    assert src["catalogue"] is not None and src["catalogue"].name == "__.csv"
    assert src["missing_years"] == [2021]
    assert any("2021" in line for line in kg.describe_sources(src))
    monkeypatch.setenv("LDT_KAGGLE_INPUT_DIR", str(tmp_path / "in"))
    monkeypatch.setenv("LDT_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("LDT_STAGE_DIR", str(tmp_path / "stage"))
    res = kg.run_event_panel_v3(kg.make_config_v3("FULL", {"taxonomy_path": str(TAX), "sensitivity_variants": []}),
                                log=lambda *a: None)
    assert res["status"] == "completed"
    manifest = json.loads((tmp_path / "out" / "event_panel_v3" / "panel_manifest_v3.json").read_text(encoding="utf-8"))
    assert manifest["missing_years"] == [2021]
    assert "нет журналов за 2021" in (tmp_path / "out" / "summary_event_panel_v3_ru.md").read_text(encoding="utf-8")


def test_row_balance_accounts_for_every_source_row(tmp_path, monkeypatch) -> None:
    """GPT 20: баланс источник → панель должен сходиться до строки (повторённый заголовок, строка без года, дубли)."""
    ev, cat = _write_inputs(tmp_path / "flat", use_7z=False)
    ds = tmp_path / "flat" / "dataset"
    csv19 = ds / "ext-journal-2019.csv"
    text = csv19.read_text(encoding="utf-8")
    header = text.splitlines()[0]
    extra = "\n".join([header, "999999999,C001,,00:00:00,f,Норма"])  # повторённый заголовок + строка без даты
    csv19.write_text(text.rstrip("\n") + "\n" + extra + "\n", encoding="utf-8")
    monkeypatch.setenv("LDT_KAGGLE_INPUT_DIR", str(tmp_path / "flat"))
    monkeypatch.setenv("LDT_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("LDT_STAGE_DIR", str(tmp_path / "stage"))
    res = kg.run_event_panel_v3(kg.make_config_v3("FULL", {"taxonomy_path": str(TAX), "sensitivity_variants": []}),
                                log=lambda *a: None)
    assert res["status"] == "completed"
    manifest = json.loads((tmp_path / "out" / "event_panel_v3" / "panel_manifest_v3.json").read_text(encoding="utf-8"))
    rb = manifest["stage"]["row_balance"]
    assert rb["unexplained"] == 0
    assert rb["header_rows_excluded"] == 1 and rb["unparseable_year_rows_excluded"] == 1
    assert rb["exact_duplicates_dropped"] == 5
    assert "необъяснённых: **0**" in (tmp_path / "out" / "summary_event_panel_v3_ru.md").read_text(encoding="utf-8")
