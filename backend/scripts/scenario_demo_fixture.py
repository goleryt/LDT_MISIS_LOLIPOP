"""Explicit synthetic raw-input fixture for a NEW isolated scenario QA database.

Never writes a prediction. Frozen workers must compute their own results.
Dates are translated together to yesterday; no new observations are filled in.
"""
import csv
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from sqlalchemy import func,select
from sqlalchemy.dialects.postgresql import insert
from app.core.config import get_settings
from app.db.models import ObjectCatalogue,ChannelCatalogue,EventsJournal
from app.db.platform import ScenarioRun
from app.db.session import SessionLocal
from app.ingestion.csv_loader import parse_event_row


def main():
    settings=get_settings()
    if settings.environment!='test' or settings.postgres_db!='ldt_combined_qa':
        raise SystemExit('Requires dedicated ENVIRONMENT=test POSTGRES_DB=ldt_combined_qa')
    root=Path('/opt/combined/vendor/examples')
    output=Path(os.environ.get('SCENARIO_FIXTURE_DIR','/qa'))
    now=datetime.now(ZoneInfo('Europe/Moscow'));day=now.date()-timedelta(days=1)
    delta=day-date(2025,8,15)
    cat=list(csv.DictReader((root/'catalogue.csv').open(encoding='utf8')))
    journal=list(csv.DictReader((root/'journal.csv').open(encoding='utf8')))
    mapping={row['ид_канала_данных']:i+1 for i,row in enumerate(cat)}
    with SessionLocal.begin() as db:
        if db.scalar(select(func.count()).select_from(ScenarioRun)):
            raise SystemExit('Scenario QA already contains runs; do not reseed')
        obj=db.get(ObjectCatalogue,1)
        if obj is None:db.add(ObjectCatalogue(ид_объект=1,диспетчерское_название_объекта='ТЕСТ — синтетический объект поставки'));db.flush()
        for row in cat:
            record={k:(mapping[row[k]] if k=='ид_канала_данных' else 1 if k=='ид_объект' else row[k]) for k in row}
            db.execute(insert(ChannelCatalogue).values(**record).on_conflict_do_update(
                index_elements=['ид_канала_данных'],set_=record))
        for i,row in enumerate(journal):
            row['ид_канала_данных']=str(mapping[row['ид_канала_данных']])
            row['ид_события']=str(900000000+i)
            row['дата']=(date.fromisoformat(row['дата'])+delta).isoformat()
            record=parse_event_row(row,row_number=i+1)
            db.execute(insert(EventsJournal).values(**record).on_conflict_do_nothing(index_elements=['d_row_hash']))
    coverage=json.loads((root/'coverage.json').read_text())
    coverage={key:(date.fromisoformat(value)+delta).isoformat() for key,value in coverage.items()}
    marker={'as_of_date':str(day),'loaded_at':now.isoformat(),'complete':True,
        'catalogue_valid_as_of':str(day),'snapshot_version':'supplier-synthetic-shifted-v1','coverage':coverage}
    output.mkdir(parents=True,exist_ok=True)
    (output/f'scenario_{day}.json').write_text(json.dumps(marker,indent=2))
    (output/f'ready_{day}.txt').write_text(str(day))
    print(json.dumps({'synthetic_raw_rows':len(journal),'channels':len(cat),'as_of_date':str(day),
        'date_translation_days':delta.days,'predictions_created':0}))


if __name__=='__main__':main()
