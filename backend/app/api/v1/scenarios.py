"""Read-only inference results and explicit human review; no inference HTTP route."""
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from app.api.v1.platform import serialize
from app.api.v1.requests import record_change, validate_target
from app.db.models import PreventiveRequest
from app.db.platform import ScenarioForecast, ScenarioRun
from app.db.session import SessionLocal
from app.scenario_job import configuration

router = APIRouter(prefix='/predictions/scenarios',tags=['experimental scenarios'])


def run_summary(row):
    context=(row.output or {}).get('evidence_context',{})
    return {'id':row.id,'as_of_date':row.as_of_date,'revision':row.revision,
        'snapshot_version':row.snapshot_version,'fingerprint':row.fingerprint,'versions':row.versions,
        'state':row.state,'error_code':row.error_code,'started_at':row.started_at,'finished_at':row.finished_at,
        'attempts':(row.output or {}).get('backend_attempt_history',[]),
        'workers':context.get('workers',{}),'worker_errors':(row.output or {}).get('worker_errors',{}),
        'recommendations':context.get('recommendations',[]),'rule_version':context.get('implementation_version'),
        'complete':context.get('complete',False),'operational_ready':False,'automated_action_allowed':False}


@router.get('')
def list_scenarios(worker:Literal['fire','sensor_failure']|None=None,
                   run_id:int|None=Query(None,ge=1),limit:int=Query(100,ge=1,le=500)):
    with SessionLocal() as db:
        runs=db.scalars(select(ScenarioRun).order_by(ScenarioRun.id.desc()).limit(30)).all()
        selected=db.get(ScenarioRun,run_id) if run_id else (runs[0] if runs else None)
        if run_id and not selected: raise HTTPException(404,'Scenario run not found')
        forecasts=[]
        if selected:
            stmt=select(ScenarioForecast).where(ScenarioForecast.run_id==selected.id).order_by(ScenarioForecast.id).limit(limit)
            if worker: stmt=stmt.where(ScenarioForecast.worker==worker)
            forecasts=[serialize(row) for row in db.scalars(stmt)]
        return {'configuration':configuration(),'run':run_summary(selected) if selected else None,
            'runs':[run_summary(row) for row in runs],'forecasts':forecasts,'has_more':len(forecasts)==limit}


class ScenarioDecisionInput(BaseModel):
    revision:int=Field(ge=1)
    decision:Literal['monitoring','reviewed','dismissed']
    notes:str=Field(min_length=1,max_length=4000)


@router.patch('/{forecast_id}/decision')
def decision(forecast_id:int,payload:ScenarioDecisionInput,request:Request):
    if not payload.notes.strip(): raise HTTPException(422,'Review requires a comment')
    with SessionLocal.begin() as db:
        row=db.scalar(select(ScenarioForecast).where(ScenarioForecast.id==forecast_id).with_for_update())
        if not row: raise HTTPException(404,'Scenario forecast not found')
        if row.revision!=payload.revision: raise HTTPException(409,'Review changed; reload it')
        row.decisions=[*row.decisions,{'actor':request.state.principal.username,'role':request.state.principal.role,
            'created_at':datetime.now(timezone.utc).isoformat(),'decision':payload.decision,'notes':payload.notes.strip()}]
        row.status=payload.decision;row.revision+=1
        request.state.audit_entity_type='scenario_forecast';request.state.audit_entity_id=str(row.id)
        return serialize(row)


@router.post('/{forecast_id}/request')
def draft(forecast_id:int,request:Request):
    with SessionLocal.begin() as db:
        row=db.scalar(select(ScenarioForecast).where(ScenarioForecast.id==forecast_id).with_for_update())
        if not row: raise HTTPException(404,'Scenario forecast not found')
        if row.request_id: return {'request_id':row.request_id}
        if not row.payload['eligible'] or row.status=='dismissed' or row.object_id is None:
            raise HTTPException(409,'A bound available forecast is required for a manual draft')
        validate_target(db,object_id=row.object_id,channel_id=row.channel_id)
        run=db.get(ScenarioRun,row.run_id)
        recs=[r['text_ru'] for r in (run.output or {}).get('evidence_context',{}).get('recommendations',[])
            if row.forecast_ref in r.get('forecast_refs',[]) and r.get('code') in {'INSPECT_SENSOR','REVIEW_FIRE_EVIDENCE'}]
        text='\n'.join(recs) or ('Вручную сверить пожарные признаки.' if row.worker=='fire' else 'Вручную проверить техническое состояние канала.')
        item=PreventiveRequest(object_id=row.object_id,channel_id=row.channel_id,status='draft',priority='medium',
            title=f'Ручная проверка сценарной оценки №{row.id}',
            description=f'Экспериментальная синтетическая оценка, не подтверждённый инцидент. Данные по {run.as_of_date}.\n{text}')
        db.add(item);db.flush();record_change(db,item,request.state.principal,None,['created_from_scenario_review'])
        row.request_id=item.id;row.revision+=1
        request.state.audit_entity_type='scenario_forecast';request.state.audit_entity_id=str(row.id)
        return {'request_id':item.id}
