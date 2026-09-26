"""Kaggle-обвязка notebook 14: сырые журналы → событийная панель v3 (части parquet) + manifest/аудит/сводка.

Шаги:
1. поиск входов в /kaggle/input: ext-journal-YYYY.{7z,csv,parquet} и справочник_каналов_датчиков.csv
   (имена сравниваются после Unicode-NFC: загрузка с macOS даёт NFD-кириллицу);
2. распаковка 7z по одному архиву → parquet только нужных колонок (все значения строками) → CSV удаляется;
3. перераскладка по календарным годам события (файл года может содержать события соседнего года;
   иначе дневные агрегаты пересеклись бы между файлами) и удаление точных дублей строк (счётчик в аудите);
4. сборка панели по группам каналов (каналы независимы) → event_panel_v3/event_panel_v3_partNN.parquet;
5. manifest с SHA-256 частей и входов, аудит и сводка — только агрегаты, без идентификаторов.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from event_panel_v3 import (EVENT_COLUMNS, SCHEMA_VERSION, SENSITIVITY_VARIANTS, TARGETS, build_event_panel,
                                csv_to_parquet, label_changes)
except ImportError:  # в notebook имена уже определены ячейкой выше
    pass

JOURNAL_RE = re.compile(r"^ext-journal-(\d{4})\.(7z|csv|parquet)$")
CATALOGUE_NAME = "справочник_каналов_датчиков.csv"
SOURCE_PRIORITY = {"parquet": 0, "csv": 1, "7z": 2}
OUTPUT_FILES = ("panel_manifest_v3.json", "audit_event_panel_v3.json", "summary_event_panel_v3_ru.md")


def make_config_v3(mode: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    if mode not in ("FULL", "SMOKE"):
        raise ValueError("MODE должен быть FULL или SMOKE")
    cfg: dict[str, Any] = {
        "mode": mode,
        "input_dir": os.environ.get("LDT_KAGGLE_INPUT_DIR", "/kaggle/input"),
        "output_dir": os.environ.get("LDT_OUTPUT_DIR", "/kaggle/working"),
        "stage_dir": os.environ.get("LDT_STAGE_DIR", "/tmp/ldt_event_panel_v3_stage"),
        "taxonomy_path": None,
        "n_buckets": 4,
        "panel": {"tau_minutes": 5},
        "smoke_years": [2019, 2020],
        "smoke_channel_share": 20,   # SMOKE: ≈1/20 каналов
        "sensitivity_variants": ["service_neutral", "power_ok_from_function"],  # отдельные сборки, в выход — только агрегаты
        "keep_stage": False,
    }
    cfg.update(overrides or {})
    return cfg


def _nfc(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def file_sha256(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


CATALOGUE_REQUIRED_COLUMNS = {"ид_канала_данных", "тип_датчика"}
YEAR_IN_PATH_RE = re.compile(r"ext-journal-(\d{4})")


def _csv_header(path: Path) -> set[str]:
    """Имена колонок первой строки CSV (для файлов, которые Kaggle переименовал: «справочник…» → «__.csv»)."""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            line = f.readline()
    except OSError:
        return set()
    return {c.strip().strip('"') for c in line.rstrip("\r\n").split(",")}


def discover_sources(input_dir: Path) -> dict[str, Any]:
    """Один источник на год (parquet > csv > 7z) и один справочник каналов.

    Сначала по имени файла; для CSV с непонятным именем — по заголовку. Kaggle при загрузке заменяет кириллицу
    в имени файла на «_» (справочник становится «__.csv») и распаковывает архивы в папки ext-journal-YYYY/."""
    by_year: dict[int, list[tuple[int, Path]]] = {}
    catalogues: list[Path] = []
    for p in sorted(Path(input_dir).rglob("*")):
        if not p.is_file():
            continue
        name = _nfc(p.name)
        m = JOURNAL_RE.match(name)
        if m:
            by_year.setdefault(int(m.group(1)), []).append((SOURCE_PRIORITY[m.group(2)], p))
            continue
        if name == CATALOGUE_NAME:
            catalogues.insert(0, p)
            continue
        if p.suffix.lower() != ".csv":
            continue
        header = _csv_header(p)
        if set(EVENT_COLUMNS) <= header:
            ym = YEAR_IN_PATH_RE.search(_nfc(str(p)))
            if ym:  # журнал с неожиданным именем файла, год — из пути (папка ext-journal-YYYY)
                by_year.setdefault(int(ym.group(1)), []).append((SOURCE_PRIORITY["csv"] + 5, p))
        elif CATALOGUE_REQUIRED_COLUMNS <= header and "значение_датчика" not in header:
            catalogues.append(p)
    journals = {y: sorted(v)[0][1] for y, v in sorted(by_year.items())}
    years = sorted(journals)
    missing = [y for y in range(years[0], years[-1] + 1) if y not in journals] if years else []
    return {"journals": journals, "ignored_duplicates": sum(len(v) - 1 for v in by_year.values()),
            "catalogue": catalogues[0] if catalogues else None, "catalogue_candidates": len(catalogues),
            "missing_years": missing}


def describe_sources(src: dict[str, Any]) -> list[str]:
    """Строки для preflight-ячейки: что найдено и чего не хватает (без содержимого файлов)."""
    lines = [f"журналы: {', '.join(str(y) for y in src['journals']) or 'не найдены'}"]
    for y, p in src["journals"].items():
        lines.append(f"  {y}: {p.parent.name}/{p.name} ({p.stat().st_size / 2**30:.2f} ГБ)")
    cat = src["catalogue"]
    lines.append(f"справочник каналов: {cat.name if cat else 'НЕ НАЙДЕН'}"
                 + (f" (кандидатов: {src['catalogue_candidates']})" if src["catalogue_candidates"] > 1 else ""))
    if src["missing_years"]:
        lines.append("ВНИМАНИЕ: нет журналов за " + ", ".join(map(str, src["missing_years"]))
                     + " — фолды ноутбука 15 обучаются на 2019–2020 и 2022+; без пропущенного года train неполный")
    return lines


def extract_7z(archive: Path, dest: Path, log: Any = print) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    exe = next((shutil.which(x) for x in ("7z", "7za", "7zr") if shutil.which(x)), None)
    if exe:
        subprocess.run([exe, "x", "-y", f"-o{dest}", str(archive)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    else:
        try:
            import py7zr  # type: ignore
        except ImportError:
            log("7z не найден — ставлю py7zr (нужен Internet в Settings ноутбука)")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "py7zr"])
                import py7zr  # type: ignore
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError("Нет распаковщика 7z: включите Internet в Settings или загрузите в dataset "
                                   "распакованные ext-journal-YYYY.csv") from exc
        with py7zr.SevenZipFile(archive, "r") as z:
            z.extractall(dest)
    return sorted(p for p in dest.rglob("*") if p.is_file() and p.suffix.lower() == ".csv")


def stage_journals(pl: Any, journals: dict[int, Path], stage_dir: Path, years: list[int] | None,
                   log: Any = print) -> tuple[list[Path], dict[str, Any]]:
    """Источники → parquet → файлы по календарному году события. Возвращает (файлы годов, аудит)."""
    raw_dir, tmp_dir, year_dir = stage_dir / "raw_parquet", stage_dir / "extract", stage_dir / "by_year"
    for d in (raw_dir, year_dir):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    audit: dict[str, Any] = {"sources": [], "years": {}}
    raw_files: list[Path] = []
    for year, src in journals.items():
        if years is not None and year not in years:
            continue
        t0 = time.time()
        entry = {"name": _nfc(src.name), "bytes": src.stat().st_size, "sha256": file_sha256(src), "rows": 0}
        if src.suffix == ".parquet":
            raw_files.append(src)
            entry["rows"] = int(pl.scan_parquet(src).select(pl.len()).collect().item())
        else:
            csvs = [src] if src.suffix == ".csv" else extract_7z(src, tmp_dir, log)
            if not csvs:
                raise RuntimeError(f"в архиве {entry['name']} нет CSV")
            for i, csv in enumerate(csvs):
                out = raw_dir / f"{src.stem}_{i}.parquet"
                entry["rows"] += csv_to_parquet(pl, csv, out)["rows"]
                raw_files.append(out)
            shutil.rmtree(tmp_dir, ignore_errors=True)
        audit["sources"].append(entry)
        log(f"{entry['name']}: {entry['rows']:,} строк → parquet за {time.time() - t0:.0f} с")
    if not raw_files:
        return [], audit
    prefix = pl.col("дата").str.slice(0, 4)
    is_header = pl.col("ид_события") == "ид_события"
    # построчный баланс по каждому источнику: повторённые строки заголовка и строки без года тоже учитываются явно
    per_file = (pl.concat([pl.scan_parquet(f).select(pl.lit(f.name).alias("_file"), is_header.alias("_hdr"),
                                                     prefix.alias("y")) for f in raw_files])
                .group_by("_file").agg(pl.col("_hdr").sum().alias("header_rows"),
                                       (~pl.col("_hdr") & ~pl.col("y").fill_null("").str.contains(r"^\d{4}$"))
                                       .sum().alias("unparseable_year_rows")).collect())
    audit["raw_files"] = {name: {"header_rows": int(h), "unparseable_year_rows": int(u)}
                          for name, h, u in per_file.iter_rows()}
    counts = (pl.scan_parquet(raw_files).filter(~is_header)
              .group_by(prefix.alias("y")).agg(pl.len()).collect())
    bad = int(counts.filter(~pl.col("y").str.contains(r"^\d{4}$") | pl.col("y").is_null())["len"].sum())
    audit["rows_with_unparseable_year_excluded"] = bad
    audit["header_rows_excluded"] = int(per_file["header_rows"].sum())
    year_files = []
    for y in sorted(counts.filter(pl.col("y").str.contains(r"^\d{4}$"))["y"].to_list()):
        if years is not None and int(y) not in years:
            audit["years"][y] = {"skipped_outside_mode_years": int(counts.filter(pl.col("y") == y)["len"][0])}
            continue
        frames = []
        for f in raw_files:
            part = pl.scan_parquet(f).select(EVENT_COLUMNS).filter((prefix == y) & (pl.col("ид_события") != "ид_события")).collect()
            if part.height:
                frames.append((f, part))
        rows = pl.concat([p for _, p in frames], how="vertical")
        n_in = rows.height
        rows = rows.unique(maintain_order=True)
        # диагностика дублей: одинаковый ид_события при разном содержимом (такие строки НЕ удаляются)
        same_id_diff = rows.height - rows.select(pl.col("ид_события").n_unique()).item()
        from_other = sum(p.height for f, p in frames if f"-{y}" not in f.name)
        out = year_dir / f"journal_{y}.parquet"
        rows.write_parquet(out, compression="zstd")
        audit["years"][y] = {"rows_in": n_in, "rows": rows.height, "exact_duplicate_rows_dropped": n_in - rows.height,
                             "same_event_id_different_content_kept": int(same_id_diff),
                             "rows_from_other_year_files": from_other}
        year_files.append(out)
        del rows, frames
    src_rows = sum(e["rows"] for e in audit["sources"])
    staged = sum(v.get("rows", 0) for v in audit["years"].values())
    dups = sum(v.get("exact_duplicate_rows_dropped", 0) for v in audit["years"].values())
    skipped = sum(v.get("skipped_outside_mode_years", 0) for v in audit["years"].values())
    audit["row_balance"] = {"source_rows": src_rows, "staged_rows": staged, "exact_duplicates_dropped": dups,
                            "header_rows_excluded": audit["header_rows_excluded"],
                            "unparseable_year_rows_excluded": bad, "skipped_outside_mode_years": skipped,
                            "unexplained": src_rows - staged - dups - audit["header_rows_excluded"] - bad - skipped}
    if not os.environ.get("LDT_KEEP_RAW_STAGE"):
        shutil.rmtree(raw_dir, ignore_errors=True)
    return year_files, audit


def _truncate_unknown(audit: dict[str, Any]) -> None:
    """Неизвестные значения — только короткие строки (не выгружать длинный свободный текст)."""
    for fa in audit.get("per_file", {}).values():
        top = fa.get("unknown_values_top30")
        if top:
            fa["unknown_values_top30"] = {str(k)[:40]: v for k, v in top.items()}


def summary_markdown(manifest: dict[str, Any], audit: dict[str, Any]) -> str:
    L = [f"# Событийная панель v3 — сводка ({manifest['mode']})", ""]
    if manifest["mode"] == "SMOKE":
        L += ["**SMOKE:** ≈1/{} каналов, годы {}. Цифры не сравнимы с FULL.".format(
            manifest["config"]["smoke_channel_share"], manifest["config"]["smoke_years"]), ""]
    L += [f"Строк (канал × сутки D): **{audit['rows']:,}**, каналов: {audit['channels']:,}, "
          f"D от {audit['date_min']} до {audit['date_max']}; граница данных {audit['data_end']}.", "",
          f"Время сборки: {manifest['runtime_s']:.0f} с; частей: {len(manifest['parts'])}.", "",
          "## Цели", "",
          "| цель | 1 | 0 | null | доля 1 среди размеченных | главные причины null |", "|---|---|---|---|---|---|"]
    for t, s in audit["targets"].items():
        null = sum(s["null_reasons"].values())
        lab = s["positive"] + s["negative"]
        top = ", ".join(f"{k} {v:,}" for k, v in sorted(s["null_reasons"].items(), key=lambda kv: -kv[1])[:3])
        L.append(f"| `{t}` | {s['positive']:,} | {s['negative']:,} | {null:,} | "
                 f"{(s['positive'] / lab if lab else float('nan')):.4f} | {top} |")
    L += ["", "## Эпизоды (секундный уровень)", "", "| вид | эпизодов | strict onset | ambiguous | медиана длит., с | ≥ τ | < τ | цензура |",
          "|---|---|---|---|---|---|---|---|"]
    for kind in ("link_episodes", "power_episodes"):
        e = audit[kind]
        med = (e["exact_duration_s_quantiles"] or {}).get("0.5")
        L.append(f"| {kind.split('_')[0]} | {e['episodes']:,} | {e['strict_onsets']:,} | {e['ambiguous_onsets']:,} | "
                 f"{med if med is not None else '—'} | {e['sustained_1']:,} | {e['sustained_0']:,} | {e['sustained_null']:,} |")
    cls: dict[str, int] = {}
    ev = 0
    for fa in audit["per_file"].values():
        ev += fa.get("events", 0)
        for k, v in fa.get("class_counts", {}).items():
            cls[k] = cls.get(k, 0) + v
    L += ["", "## Классы значений", "", "| класс | событий | доля |", "|---|---|---|"]
    for k, v in sorted(cls.items(), key=lambda kv: -kv[1]):
        L.append(f"| {k} | {v:,} | {v / max(ev, 1):.4f} |")
    unk = cls.get("unknown_value", 0) / max(ev, 1)
    L += ["", "## Предупреждения", ""]
    warn = []
    if unk > 0.01:
        warn.append(f"- доля неизвестных значений {unk:.3f} > 1 % — дополнить таксономию до обучения")
    t2a = audit["targets"]["target_t2a_link_onset"]
    unobs = t2a["null_reasons"].get("unobserved_window", 0)
    if unobs > t2a["positive"] + t2a["negative"]:
        warn.append(f"- T2a: окон без событий ({unobs:,}) больше, чем размеченных — событийные каналы молчат; "
                    "coverage показывать отдельно")
    stage = manifest["stage"]
    moved = sum(v.get("rows_from_other_year_files", 0) for v in stage["years"].values())
    dups = sum(v.get("exact_duplicate_rows_dropped", 0) for v in stage["years"].values())
    rb = stage.get("row_balance", {})
    if rb:
        L_rb = (f"- баланс строк: источники {rb['source_rows']:,} = в панель {rb['staged_rows']:,} + точные дубли "
                f"{rb['exact_duplicates_dropped']:,} + строки заголовка {rb['header_rows_excluded']:,} + без года "
                f"{rb['unparseable_year_rows_excluded']:,} + вне режима {rb['skipped_outside_mode_years']:,}; "
                f"необъяснённых: **{rb['unexplained']:,}**")
        warn.append(L_rb)
    if manifest.get("missing_years"):
        warn.append("- **нет журналов за " + ", ".join(map(str, manifest["missing_years"])) + "** — панель неполная, "
                    "train фолдов ноутбука 15 без этого года")
    if moved:
        warn.append(f"- {moved:,} строк лежали в файле другого года — перенесены по дате события")
    if dups:
        warn.append(f"- удалено точных дублей строк: {dups:,}")
    L += warn or ["- нет"]
    sm = {}
    for fa in audit["per_file"].values():
        for stream, counts in fa.get("stream_mapping", {}).items():
            if stream == "events_in_no_stream_by_class":
                continue
            for k, v in counts.items():
                sm.setdefault(stream, {}).setdefault(k, 0)
                sm[stream][k] += v
    if sm:
        L += ["", f"## Потоки (stream mapping {manifest['panel_config'].get('stream_mapping_version', '?')}): секунды по состоянию", "",
              "| поток | F | O | A (конфликт) | A (неизвестно) | без сведений |", "|---|---|---|---|---|---|"]
        for stream, c in sm.items():
            L.append(f"| {stream} | {c.get('F', 0):,} | {c.get('O', 0):,} | {c.get('A_conflict', 0):,} | "
                     f"{c.get('A_unknown', 0):,} | {c.get('none', 0):,} |")
    if audit.get("sensitivity"):
        L += ["", "## Sensitivity-версии разметки (заранее объявлены; выбор не по validation-метрикам)", ""]
        for name, sv in audit["sensitivity"].items():
            L.append(f"**{name}** ({sv['config']}): изменений меток —")
            for t, ch in sv["label_changes"].items():
                if ch:
                    L.append(f"- `{t}`: " + ", ".join(f"{k} {v:,}" for k, v in ch.items()))
            L.append("")
    L += ["", "Метки — наблюдаемые события журнала (потеря связи, обесточивание, технические значения, газ ≥ 1 %), "
          "не подтверждённые физические отказы. Правила: docs/EVENT_PANEL_V3_RU.md.", ""]
    return "\n".join(L)


def run_event_panel_v3(cfg: dict[str, Any], log: Any = print) -> dict[str, Any]:
    import polars as pl

    t_start = time.time()
    out = Path(cfg["output_dir"])
    panel_dir = out / "event_panel_v3"
    shutil.rmtree(panel_dir, ignore_errors=True)
    panel_dir.mkdir(parents=True)
    src = discover_sources(Path(cfg["input_dir"]))
    if not src["journals"] or src["catalogue"] is None:
        return {"status": "stopped", "stop_reason": "не найдены ext-journal-YYYY.* или " + CATALOGUE_NAME
                + " во входах (Add Input → приватный dataset)"}
    smoke = cfg["mode"] == "SMOKE"
    years = cfg["smoke_years"] if smoke else None
    log(f"входы: годы {list(src['journals'])}, справочник найден; режим {cfg['mode']}")
    year_files, stage = stage_journals(pl, src["journals"], Path(cfg["stage_dir"]), years, log)
    if not year_files:
        return {"status": "stopped", "stop_reason": "после отбора годов не осталось журналов"}
    channel_filter = (pl.col("ид_канала_данных").hash(seed=7) % cfg["smoke_channel_share"] == 0) if smoke else None
    _, audit = build_event_panel(pl, year_files, src["catalogue"], Path(cfg["taxonomy_path"]), config=cfg["panel"],
                                 log=log, n_buckets=cfg["n_buckets"], out_dir=panel_dir, channel_filter=channel_filter)
    _truncate_unknown(audit)
    audit["sensitivity"] = {}
    key_cols = ["d_channel_key", "d_cutoff_date"] + TARGETS
    main_labels = pl.read_parquet([panel_dir / p for p in audit["part_files"]], columns=key_cols)
    for name in cfg.get("sensitivity_variants", []):
        vdir = Path(cfg["stage_dir"]) / f"sensitivity_{name}"
        shutil.rmtree(vdir, ignore_errors=True)
        vdir.mkdir(parents=True)
        log(f"sensitivity «{name}»: пересборка разметки")
        _, va = build_event_panel(pl, year_files, src["catalogue"], Path(cfg["taxonomy_path"]),
                                  config={**cfg["panel"], **SENSITIVITY_VARIANTS[name]}, log=lambda *a: None,
                                  n_buckets=cfg["n_buckets"], out_dir=vdir, channel_filter=channel_filter)
        var_labels = pl.read_parquet([vdir / p for p in va["part_files"]], columns=key_cols)
        audit["sensitivity"][name] = {"config": SENSITIVITY_VARIANTS[name],
                                      "label_changes": label_changes(pl, main_labels, var_labels),
                                      "targets": {t: {k: v for k, v in va["targets"][t].items() if k != "by_year"}
                                                  for t in TARGETS}}
        shutil.rmtree(vdir, ignore_errors=True)
    del main_labels
    parts = []
    for name in audit["part_files"]:
        p = panel_dir / name
        parts.append({"file": name, "bytes": p.stat().st_size, "sha256": file_sha256(p),
                      "rows": int(pl.scan_parquet(p).select(pl.len()).collect().item())})
    manifest = {
        "schema_version": SCHEMA_VERSION, "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": cfg["mode"], "status": "completed_smoke_non_comparable" if smoke else "completed",
        "config": {k: v for k, v in cfg.items() if k not in ("input_dir", "output_dir", "stage_dir", "taxonomy_path")},
        "panel_config": audit["config"], "taxonomy_version": audit["taxonomy_version"],
        "taxonomy_sha256": audit["taxonomy_sha256"], "data_end": audit["data_end"],
        "catalogue": {"bytes": src["catalogue"].stat().st_size, "sha256": file_sha256(src["catalogue"]),
                      "candidates_found": src["catalogue_candidates"]},
        "sources_ignored_as_duplicates": src["ignored_duplicates"], "missing_years": src["missing_years"],
        "stage": stage, "parts": parts,
        "rows": audit["rows"], "channels": audit["channels"],
        "key_columns": ["d_channel_key", "d_cutoff_date"], "feature_columns": audit["feature_columns"],
        "target_columns": audit["target_columns"],
        "reason_columns": ["reason_" + t[len("target_"):] for t in audit["target_columns"]],
        "purge_column": "d_label_decision_end", "polars_version": pl.__version__,
        "runtime_s": round(time.time() - t_start, 1),
    }
    (panel_dir / "panel_manifest_v3.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "audit_event_panel_v3.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out / "summary_event_panel_v3_ru.md").write_text(summary_markdown(manifest, audit), encoding="utf-8")
    if not cfg["keep_stage"]:
        shutil.rmtree(cfg["stage_dir"], ignore_errors=True)
    return {"status": manifest["status"], "rows": audit["rows"], "channels": audit["channels"],
            "runtime_s": manifest["runtime_s"], "panel_dir": str(panel_dir)}
