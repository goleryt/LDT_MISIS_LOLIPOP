"""Acceptance: shipped real model on clearly synthetic input in a TEST database only.

This measures software integration, never predictive quality on real incidents.
Run after seed_test_data and empty-state browser tests.
"""
import csv
import json
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from sqlalchemy import func, select
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.platform import MlRun, MlScore, Notification, Prediction
from app.ml_job import last_closed_day, run_daily, MlJobError

def main():
    settings = get_settings()
    if settings.environment != 'test':
        raise SystemExit('Only ENVIRONMENT=test is allowed')
    d = last_closed_day(settings)
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(MlRun)):
            raise SystemExit('Acceptance requires a fresh test ML journal')
        notices_before = db.scalar(select(func.count()).select_from(Notification))
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cat = root / 'catalogue.csv'
        with cat.open('w',encoding='utf-8',newline='') as handle:
            writer=csv.writer(handle)
            writer.writerow(['ид_канала_данных','ид_объект','тип_датчика','тип_инж_системы'])
            writer.writerow([1,1,'Газовый датчик','Газ'])
        journal=root/'journal.csv'
        with journal.open('w',encoding='utf-8',newline='') as handle:
            writer=csv.writer(handle)
            writer.writerow(['ид_события','ид_канала_данных','дата','время','тревожное','значение_датчика'])
            for n in range(430):
                day=d-timedelta(days=429-n)
                for hour in (0,8,16):
                    writer.writerow([n*3+hour+1,1,day.isoformat(),f'{hour:02}:00:00','false',f'{0.2+(n%11)*0.01:.2f}'])
        marker=root/'ready.txt';marker.write_text(d.isoformat())
        started=time.perf_counter()
        result=run_daily(d,settings,journal_files=[journal],catalogue_file=cat,ready_marker=marker)
        assert result['gas_scored']==1 and result['predictions_created']==1,result
        repeated=run_daily(d,settings,journal_files=[journal],catalogue_file=cat,ready_marker=marker)
        assert repeated['state']=='already_written'
        with SessionLocal() as db:
            pred=db.scalar(select(Prediction))
            assert pred.ml_metadata['decision_status']=='experimental_shadow'
            assert pred.ml_metadata['window_start']==str(d+timedelta(days=2))
            assert pred.ml_metadata['window_end_exclusive']==str(d+timedelta(days=3))
            assert pred.recommendation and pred.request_id is None
            assert db.scalar(select(func.count()).select_from(Notification))==notices_before
            assert db.scalar(select(func.count()).select_from(MlScore).where(MlScore.kind=='incident'))==0
        with journal.open('a') as handle: handle.write('\n')
        try:
            run_daily(d,settings,journal_files=[journal],catalogue_file=cat,ready_marker=marker)
        except MlJobError as exc:
            assert str(exc)=='INPUT_CHANGED_USE_NEW_REVISION'
        else: raise AssertionError('Changed input was accepted without revision')
        print(json.dumps({'scenario':'real_model_on_synthetic_inputs','checks':'inference, provenance, window, recommendation, idempotence, no auto-alert, no stub incident, changed-input rejection','seconds':round(time.perf_counter()-started,3),'rows':result['gas_scored']},ensure_ascii=False))
if __name__=='__main__': main()
