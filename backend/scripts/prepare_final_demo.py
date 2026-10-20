"""Guarded demo inventory, with opt-in idempotent publication of a fixed snapshot.

Default is read-only. Does not seed at startup, delete data, modify scores,
or copy an existing forecast onto another object. Opt-in gas preparation adds
only the original clearly synthetic observations and runs the frozen runtime;
an existing complete historical gas calculation is reused unchanged.
"""
import argparse
from datetime import date
import hashlib
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from app.db.models import ChannelCatalogue, ObjectCatalogue, EventsJournal
from app.db.platform import MlScore, Prediction, ScenarioRun, ScenarioForecast, AuditEntry
from app.db.session import SessionLocal, engine
from scripts.publish_synthetic_scenario_demo import PROJECT, ENVIRONMENT, OBJECT_ID, LABEL, publish
from scripts.final_demo_inputs import export_gas_inputs, DAY, CHANNELS

VERSION = 'final-demo-2026-10-v1'
GAS_OBJECT = 900000001


def publish_gas():
    """Explicit gas-runtime operation, independent of the SF/Fire environment."""
    if os.environ.get('PUBLISH_FINAL_GAS_DEMO') != 'synthetic-input-only':
        raise RuntimeError('EXPLICIT_GAS_DEMO_ACCEPTANCE_REQUIRED')
    inventory()  # Reject reserved-ID collisions before modifying any catalogue.
    with SessionLocal() as db:
        old=db.scalars(select(MlScore).where(MlScore.object_id==GAS_OBJECT,MlScore.as_of_date==DAY,
            MlScore.kind=='gas')).all()
        if len(old)==3 and {r.channel_id for r in old}==set(CHANNELS):
            return {'reused':True,'as_of_date':str(DAY),'score_ids':[r.id for r in old],
                'inference':'previous saved real gas runtime; no new computation'}
    # Fail before writes when accidentally invoked in the web API environment.
    from app.ml_runtime.lct_ml_runtime import MLRuntime  # noqa: F401
    from app.ml_job import run_daily
    from app.ingestion.import_registry import import_events_file
    with SessionLocal.begin() as db:
        obj=db.get(ObjectCatalogue,GAS_OBJECT)
        if not obj:db.add(ObjectCatalogue(ид_объект=GAS_OBJECT,вид_объекта='DEMO',
            диспетчерское_название_объекта='СИНТЕТИЧЕСКИЙ DEMO — газовые датчики'))
        db.flush()
        for i,cid in enumerate(CHANNELS):
            old=db.get(ChannelCatalogue,cid)
            if old and old.ид_объект!=GAS_OBJECT:raise RuntimeError('DEMO_CHANNEL_ID_COLLISION')
            if not old:db.add(ChannelCatalogue(ид_канала_данных=cid,ид_объект=GAS_OBJECT,
                тип_датчика='Газовый датчик',тип_инж_системы='Газ',название_датчика=f'СИНТЕТИЧЕСКИЙ DEMO — газ {i+1}'))
    with tempfile.TemporaryDirectory(prefix='final_demo_inputs_') as directory:
        root=Path(directory);inputs=export_gas_inputs(root)
        journal=root/'synthetic-demo-journal-20260928.csv'
        imported=import_events_file(journal,original_file_name=journal.name,import_type='events_journal')
        marker=root/'ready.txt';marker.write_text(str(DAY),encoding='utf8')
        result=run_daily(DAY,journal_files=[journal],catalogue_file=root/'synthetic-demo-catalogue.csv',ready_marker=marker)
    with SessionLocal.begin() as db:
        for prediction in db.scalars(select(Prediction).where(Prediction.object_id==GAS_OBJECT)):
            prediction.ml_metadata={**(prediction.ml_metadata or {}),'data_origin':'synthetic_demo',
                'data_notice':'Настоящий frozen gas runtime на искусственной истории; не реальный объект.'}
        db.add(AuditEntry(request_id=str(uuid4()),actor='system:final-demo',role='system',action='CREATE',
            target='operator:prepare_final_demo:gas',entity_type='ml_run',entity_id=str(DAY),outcome=200))
    return {'reused':False,'inputs':inputs,'import_status':imported['status'],'inference':result}


def verify_target(expected_database):
    if not expected_database or engine.url.database != expected_database:
        raise RuntimeError('DEMO_DATABASE_IDENTITY_MISMATCH')
    if os.environ.get('ENVIRONMENT') == 'production':
        if (os.environ.get('RAILWAY_PROJECT_ID') != PROJECT or
                os.environ.get('RAILWAY_ENVIRONMENT_ID') != ENVIRONMENT):
            raise RuntimeError('UNKNOWN_PUBLIC_DEMO_TARGET')
    elif os.environ.get('ENVIRONMENT') != 'test':
        raise RuntimeError('DEMO_REQUIRES_IDENTIFIED_TEST_OR_PUBLIC_DEMO')


def inventory():
    def checksum(value):
        return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str,
            separators=(',',':')).encode('utf8')).hexdigest()
    with SessionLocal() as db:
        objects = db.scalars(select(ObjectCatalogue).where(ObjectCatalogue.ид_объект.in_([GAS_OBJECT,OBJECT_ID]))).all()
        names = {GAS_OBJECT:'СИНТЕТИЧЕСКИЙ DEMO — газовые датчики',OBJECT_ID:LABEL}
        if any(o.диспетчерское_название_объекта != names[o.ид_объект] for o in objects):
            raise RuntimeError('DEMO_CATALOGUE_ID_COLLISION')
        catalogue = db.scalars(select(ChannelCatalogue).where(ChannelCatalogue.ид_объект.in_([GAS_OBJECT,OBJECT_ID]))).all()
        gas = db.scalars(select(MlScore).where(MlScore.object_id==GAS_OBJECT).order_by(MlScore.id)).all()
        runs = db.scalars(select(ScenarioRun).order_by(ScenarioRun.id)).all()
        runs = [r for r in runs if (r.snapshot.get('provenance') or {}).get('kind') == 'supplier_synthetic_demo']
        scenario=[]
        for run in runs:
            forecasts=db.scalars(select(ScenarioForecast).where(ScenarioForecast.run_id==run.id).order_by(ScenarioForecast.id)).all()
            scenario.append({'id':run.id,'as_of_date':str(run.as_of_date),'snapshot_version':run.snapshot_version,
                'input_fingerprint':run.fingerprint,'snapshot_sha256':checksum(run.snapshot),
                'versions':run.versions,'state':run.state,'provenance':run.snapshot.get('provenance'),
                'output_sha256':checksum(run.output),'forecast_ids':[r.id for r in forecasts],
                'scores':[{'worker':r.worker,'object_id':r.object_id,'channel_id':r.channel_id,
                    'score':r.payload.get('score'),'eligible':r.payload.get('eligible'),
                    'window_start':r.payload.get('window_start'),'window_end_exclusive':r.payload.get('window_end_exclusive'),
                    'model_version':r.payload.get('model_version')} for r in forecasts]})
        source_events = [dict(row) for row in db.execute(select(EventsJournal.__table__).where(
            EventsJournal.ид_канала_данных.in_([c.ид_канала_данных for c in catalogue if c.ид_объект==GAS_OBJECT]))
            .order_by(EventsJournal.id)).mappings()]
        return {'dataset_version':VERSION,'mode':'read_only_inventory','deletion_performed':False,
            'operational_events_written':False,'new_inference_performed':False,
            'objects':[{'id':o.ид_объект,'name':o.диспетчерское_название_объекта,'synthetic':True} for o in objects],
            'bindings':[{'channel_id':c.ид_канала_данных,'object_id':c.ид_объект,'type':c.тип_датчика} for c in catalogue],
            'gas':[{'id':g.id,'run_id':g.run_id,'as_of_date':str(g.as_of_date),'object_id':g.object_id,'channel_id':g.channel_id,
                'score':g.score,'score_kind':g.score_kind,'window_start':str(g.window_start),
                'window_end_exclusive':str(g.window_end_exclusive),'model_version':g.model_version,
                'immutable_payload_sha256':checksum(g.payload)} for g in gas],
            'gas_source_event_count':len(source_events),'gas_source_events_sha256':checksum(source_events),
            'scenarios':scenario,'limitations':['Gas is a saved historical shadow/proxy result, not a new current-day calculation.',
                'SF/Fire are real frozen inference on supplier synthetic observations.',
                'No shared incident probability, no automatic critical actions, schematic locations only.',
                'Unknown-origin QA records and all operational history/audit are retained.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-database',required=True)
    parser.add_argument('--publish-scenarios',action='store_true',help='Explicit write; existing operator opt-ins also required')
    parser.add_argument('--publish-gas',action='store_true',help='Separate gas runtime only; explicit gas opt-in required')
    parser.add_argument('--as-of-date',type=date.fromisoformat,default=date(2026,10,18))
    parser.add_argument('--export-gas-inputs',help='Export original fixed synthetic CSV inputs only; no DB write or inference')
    args=parser.parse_args();verify_target(args.expected_database)
    if args.export_gas_inputs:
        print(json.dumps({'gas_inputs':export_gas_inputs(args.export_gas_inputs)},ensure_ascii=False))
    if args.publish_gas:
        print(json.dumps({'gas_publication':publish_gas()},ensure_ascii=False,default=str))
    if args.publish_scenarios:
        result=publish(as_of_date=args.as_of_date)
        print(json.dumps({'publication':result},ensure_ascii=False))
    print(json.dumps(inventory(),ensure_ascii=False,default=str,indent=2))


if __name__=='__main__':
    main()
