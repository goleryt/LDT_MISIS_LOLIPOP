"""Command-line entry point for channel-panel construction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from panel import build_panel


def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--failure-state-dictionary",
        type=Path,
        default=here / "config" / "failure_state_dictionary.json",
    )
    parser.add_argument(
        "--latency-minutes", type=int, nargs="+", default=[0, 5, 60, 360, 1440]
    )
    parser.add_argument("--target-lead-hours", type=int, default=24)
    parser.add_argument("--target-window-hours", type=int, default=24)
    parser.add_argument("--clean-history-days", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for latency in args.latency_minutes:
        panel, audit = build_panel(
            args.data_dir,
            args.failure_state_dictionary,
            latency,
            target_lead_hours=args.target_lead_hours,
            target_window_hours=args.target_window_hours,
            clean_history_days=args.clean_history_days,
        )
        suffix = f"latency_{latency:04d}m"
        panel.write_parquet(
            args.output_dir / f"channel_panel_{suffix}.parquet",
            compression="zstd",
        )
        (args.output_dir / f"panel_audit_{suffix}.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
