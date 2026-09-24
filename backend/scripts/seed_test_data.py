"""Opt-in synthetic monitoring fixtures for CI/smoke/load tests; never produces predictions."""
import os
from datetime import datetime, timedelta
from sqlalchemy.dialects.postgresql import insert
from app.core.config import get_settings
from app.core.security import password_hash
from app.db.models import ObjectCatalogue, ChannelCatalogue, EventsJournal
from app.db.platform import User
from app.db.session import SessionLocal
from app.ingestion.csv_loader import parse_event_row

def main():
    if get_settings().environment != "test":
        raise SystemExit("Only ENVIRONMENT=test permits test fixtures")
    username = os.environ.get("TEST_USERNAME", "dispatcher")
    password = os.environ["TEST_PASSWORD"]
    rows = int(os.environ.get("SEED_EVENT_COUNT", "20000"))
    with SessionLocal.begin() as db:
        db.execute(insert(User).values(username=username,role="dispatcher",provider="local",active=True,password_hash=password_hash(password))
                   .on_conflict_do_nothing(index_elements=["username"]))
        db.execute(insert(ObjectCatalogue).values([{"ид_объект":i,"диспетчерское_название_объекта":f"ТЕСТ — объект {i}"} for i in range(1,51)])
                   .on_conflict_do_nothing(index_elements=["ид_объект"]))
        db.execute(insert(ChannelCatalogue).values([{"ид_канала_данных":i,"ид_объект":((i-1)//20)+1,
                   "название_датчика":f"ТЕСТ — датчик {i}","тип_датчика":"temperature"} for i in range(1,1001)])
                   .on_conflict_do_nothing(index_elements=["ид_канала_данных"]))
        start=datetime(2026,9,1)
        batch=[]
        for i in range(1,rows+1):
            when=start+timedelta(seconds=i)
            batch.append(parse_event_row({"ид_события":str(i),"ид_канала_данных":str((i-1)%1000+1),
                         "дата":when.date().isoformat(),"время":when.time().isoformat(),
                         "тревожное":str(i%20==0).lower(),"значение_датчика":"25"},row_number=i))
            if len(batch)==1000:
                db.execute(insert(EventsJournal).values(batch).on_conflict_do_nothing(index_elements=["d_row_hash"])); batch=[]
        if batch:
            db.execute(insert(EventsJournal).values(batch).on_conflict_do_nothing(index_elements=["d_row_hash"]))
    print(f"Synthetic monitoring fixture ready: 50 objects, 1000 sensors, up to {rows} events; no predictions.")

if __name__=="__main__":
    main()
