"""Daily batch after ETL's date marker, retries failures; no fabricated data or marker."""
import logging
import os
import time
from pathlib import Path
from app.core.config import get_settings
from app.ml_job import last_closed_day, run_daily
from app.operations import heartbeat

def main():
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    ready = Path(os.environ.get("ML_READY_DIR", "/ready"))
    completed = None
    while True:
        day = last_closed_day(settings)
        marker = ready / f"ready_{day}.txt"
        heartbeat("ml_scheduler", "waiting_for_marker" if not marker.is_file() else "idle")
        if day != completed and marker.is_file():
            try:
                result = run_daily(day, ready_marker=marker)
                logging.info("ML daily state=%s day=%s selected=%s", result["state"], day, result.get("alerts_selected", 0))
                completed = day
                heartbeat("ml_scheduler", "completed", success=True)
            except Exception as exc:
                heartbeat("ml_scheduler", "error", error_code=type(exc).__name__)
                logging.error("ML daily failed day=%s type=%s; inspect /predictions/runs", day, type(exc).__name__)
        time.sleep(300)
if __name__ == "__main__": main()
