"""One completed day -> one immutable, retry-safe ML forecast journal file.

This is an ML-side batch entry point. The backend/operations scheduler decides
when to invoke it and how to ingest the JSON; this module never sends alerts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

JOB_VERSION = "daily-forecast-job-v1"


def _day(value: str | date | None) -> date:
    if value is None:
        return date.today() - timedelta(days=1)
    if isinstance(value, date):
        result = value
    else:
        if len(value) != 10 or value[4] != "-" or value[7] != "-":
            raise ValueError("as_of_date must be YYYY-MM-DD")
        result = date.fromisoformat(value)
    if result >= date.today():
        raise ValueError("as_of_date must be a completed day before today")
    return result


def _snapshot(paths: list[Path]) -> str:
    """Fingerprint file identity and metadata; reject changes during scoring."""
    rows = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        stat = path.stat()
        rows.append([str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns])
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()


def _optional_rows(path: Path | None, label: str) -> list[dict[str, Any]] | None:
    if path is None:
        return None
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{label} must be a JSON array of objects")
    return rows


def run_daily(journal_files: list[str | Path], catalogue_file: str | Path,
              bundles_dir: str | Path, output_dir: str | Path,
              as_of_date: str | date | None = None, revision: int = 1,
              ready_marker: str | Path | None = None,
              ppr_windows_file: str | Path | None = None,
              recent_incidents_file: str | Path | None = None,
              runtime_factory: Callable[[Path], Any] | None = None,
              break_stale_lock_hours: float | None = None) -> dict[str, Any]:
    day = _day(as_of_date)
    if revision < 1:
        raise ValueError("revision must be >= 1")
    if break_stale_lock_hours is not None and break_stale_lock_hours <= 0:
        raise ValueError("break_stale_lock_hours must be > 0")
    if not journal_files:
        raise ValueError("at least one journal file is required")
    journals = [Path(p) for p in journal_files]
    catalogue, bundles, output = Path(catalogue_file), Path(bundles_dir), Path(output_dir)
    if not bundles.is_dir():
        raise FileNotFoundError(bundles)
    marker = Path(ready_marker) if ready_marker is not None else None
    if marker is not None and marker.read_text(encoding="utf-8").strip() != day.isoformat():
        raise ValueError("ready marker does not match as_of_date")
    ppr = Path(ppr_windows_file) if ppr_windows_file is not None else None
    recent = Path(recent_incidents_file) if recent_incidents_file is not None else None
    ppr_rows = _optional_rows(ppr, "ppr_windows")
    recent_rows = _optional_rows(recent, "recent_incidents")
    bundle_files = sorted(p for p in bundles.iterdir() if p.is_file() and
                          (p.suffix == ".zip" or p.name.endswith(".zip.sha256") or p.name == "ACTIVE.json"))
    if not bundle_files:
        raise ValueError("bundles_dir has no bundle files")
    sources = [*journals, catalogue, *bundle_files, *([ppr] if ppr else []),
               *([recent] if recent else []), *([marker] if marker else [])]
    fingerprint = _snapshot(sources)
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"forecast_{day.isoformat()}_r{revision}.json"
    lock = output / f"forecast_{day.isoformat()}_r{revision}.lock"
    for attempt in range(2):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError as exc:
            stat = lock.stat()
            age_hours = max(0.0, (datetime.now(timezone.utc).timestamp() - stat.st_mtime) / 3600)
            if (attempt == 0 and break_stale_lock_hours is not None and
                    age_hours >= break_stale_lock_hours and
                    lock.stat().st_mtime_ns == stat.st_mtime_ns):
                lock.unlink()
                continue
            raise RuntimeError(
                f"daily calculation lock exists: {lock} (age {age_hours:.2f} h); "
                "verify the previous job is stopped before using --break-stale-lock-hours"
            ) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump({"pid": os.getpid(), "host": socket.gethostname(),
                   "started_at_utc": datetime.now(timezone.utc).isoformat()}, handle)
        handle.write("\n")
    try:
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if (existing.get("job_version") != JOB_VERSION or
                    existing.get("input_fingerprint") != fingerprint):
                raise ValueError("revision already exists for different inputs; use a new revision")
            return {"status": "already_written", "path": str(target),
                    "gas_count": existing["gas_count"], "incident_count": existing["incident_count"]}

        if runtime_factory is None:
            from lct_ml_runtime import MLRuntime
            runtime_factory = MLRuntime
        request_id = f"daily-{day.isoformat()}-r{revision}"
        scored = runtime_factory(bundles).score_day(
            journals, catalogue, day, request_id=request_id,
            ppr_windows=ppr_rows, recent_incidents=recent_rows)
        if scored.get("as_of_date") != day.isoformat() or scored.get("request_id") != request_id:
            raise ValueError("runtime returned a different day or request_id")
        gas, incidents = scored.get("gas"), scored.get("incidents")
        if not isinstance(gas, list) or not isinstance(incidents, list) or not (gas or incidents):
            raise ValueError("runtime returned no forecast rows")
        if any(not isinstance(row, dict) or "recommendation" not in row for row in gas + incidents):
            raise ValueError("runtime output is missing recommendation fields")
        if _snapshot(sources) != fingerprint:
            raise RuntimeError("input files changed while scoring; no journal was written")
        envelope = {"job_version": JOB_VERSION, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "as_of_date": day.isoformat(), "revision": revision,
                    "input_fingerprint": fingerprint, "gas_count": len(gas),
                    "incident_count": len(incidents), "forecast": scored}
        encoded = json.dumps(envelope, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n"
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output,
                                             prefix=f".{target.stem}.", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return {"status": "written", "path": str(target),
                "gas_count": len(gas), "incident_count": len(incidents)}
    finally:
        lock.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", action="append", required=True, help="Repeat for each historical CSV/parquet")
    parser.add_argument("--catalogue", required=True)
    parser.add_argument("--bundles-dir", required=True)
    parser.add_argument("--output-dir", default="data/forecast_journal")
    parser.add_argument("--as-of-date", help="Completed day YYYY-MM-DD; default is yesterday in scheduler timezone")
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument("--ready-marker", help="Optional UTF-8 file containing the completed as_of_date")
    parser.add_argument("--ppr-windows-file", help="Optional JSON array of verified PPR windows")
    parser.add_argument("--recent-incidents-file", help="Optional JSON array of confirmed recent incidents")
    parser.add_argument("--break-stale-lock-hours", type=float,
                        help="After checking the previous job is stopped, remove a lock at least N hours old")
    args = parser.parse_args()
    result = run_daily(args.journal, args.catalogue, args.bundles_dir, args.output_dir,
                       args.as_of_date, args.revision, args.ready_marker,
                       args.ppr_windows_file, args.recent_incidents_file,
                       break_stale_lock_hours=args.break_stale_lock_hours)
    print(json.dumps(result, ensure_ascii=False))  # counts/path only, never row identifiers


if __name__ == "__main__":
    main()
