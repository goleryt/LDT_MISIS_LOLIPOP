"""Daily ML batch entry point. Needs the ML environment (see app/ml_job.py)."""
import argparse
import json
import logging
from datetime import date

from app.ml_job import MlJobError, run_daily


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=None,
                        help="day D, YYYY-MM-DD (default: the last closed day)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        summary = run_daily(args.date)
    except MlJobError as exc:
        raise SystemExit(f"ML run failed: {exc}") from None
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
