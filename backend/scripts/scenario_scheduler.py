"""Independent opt-in scheduler. No marker, no inference; no automatic retry loop."""
from datetime import datetime, timedelta
import logging
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo
from app.core.config import get_settings
from app.operations import heartbeat
from app.scenario_job import run_scenarios


def main():
    logging.basicConfig(level=logging.INFO)
    settings=get_settings()
    completed=None
    while True:
        if not settings.scenario_enabled:
            heartbeat('scenario_worker','disabled');time.sleep(300);continue
        day=datetime.now(ZoneInfo('Europe/Moscow')).date()-timedelta(days=1)
        marker=Path(os.environ.get('SCENARIO_READY_DIR','/scenario-ready'))/f'scenario_{day}.json'
        heartbeat('scenario_worker','waiting_for_marker' if not marker.is_file() else 'idle')
        if marker.is_file() and completed!=day:
            try:
                result=run_scenarios(marker,settings=settings)
                logging.info('Scenario batch id=%s state=%s',result['id'],result['state'])
            except Exception as exc:
                heartbeat('scenario_worker','error',error_code=type(exc).__name__)
                logging.error('Scenario batch failed type=%s; manual correction/retry required',type(exc).__name__)
            # Insufficient history/unavailable model does not cause endless inference.
            completed=day
        time.sleep(300)


if __name__=='__main__': main()
