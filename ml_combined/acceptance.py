"""Bounded real inference acceptance, synthetic supplier inputs; no database.

Run in the standalone container with no network/credentials. Rule-only fixtures
are never promoted to application forecasts. No training/threshold selection.
"""
import csv
from copy import deepcopy
import json
from pathlib import Path
import resource
import sys
import time
from compute import HOME, compute, daily_json


def main():
    started=time.monotonic();root=HOME/'vendor'
    import pandas as pd
    precision_value=0.12345678901234567
    assert json.loads(daily_json(pd.DataFrame({'num_mean':[precision_value],'missing':[float('nan')]})))[0]=={'num_mean':precision_value,'missing':None}
    if Path('/app/app/scenario_registry.json').is_file():
        assert json.loads(Path('/app/app/scenario_registry.json').read_text())==json.loads((root/'examples/registry.json').read_text())
    catalogue=list(csv.DictReader((root/'examples/catalogue.csv').open(encoding='utf8')))
    journal=list(csv.DictReader((root/'examples/journal.csv').open(encoding='utf8')))
    mapping={r['ид_канала_данных']:str(i+1) for i,r in enumerate(catalogue)}
    for row in catalogue:row['ид_канала_данных']=mapping[row['ид_канала_данных']];row['ид_объект']='1'
    for row in journal:row['ид_канала_данных']=mapping[row['ид_канала_данных']]
    snapshot={'as_of_date':'2025-08-15','snapshot_version':'supplier-raw-numeric-ids-v1',
        'coverage':json.loads((root/'examples/coverage.json').read_text()),'catalogue':catalogue,
        'journal':journal,'gas':None,'gas_issued_at':None}
    issued='2025-08-16T06:00:00+03:00'
    actual=compute(snapshot,issued_at=issued)
    rows=actual['evidence_context']['forecasts']
    assert len(rows)==3 and all(r['eligible'] for r in rows)
    assert {r['worker'] for r in rows}=={'sensor_failure','fire'}
    assert not actual['worker_errors']
    assert actual['evidence_context']['automated_action_allowed'] is False
    original=json.loads((root/'examples/actual_three_model_replay.json').read_text())
    for worker in ('sensor_failure','fire'):
        left=sorted(r['score'] for r in rows if r['worker']==worker)
        right=sorted(r['score'] for r in original['evidence_context']['forecasts'] if r['worker']==worker)
        assert len(left)==len(right) and all(abs(a-b)<1e-12 for a,b in zip(left,right))
    reverse=deepcopy(snapshot);reverse['journal'].reverse()
    assert compute(reverse,issued_at=issued)==actual
    future=deepcopy(snapshot);row=deepcopy(journal[-1]);row['дата']='2025-08-16';future['journal'].append(row)
    assert compute(future,issued_at=issued)==actual
    missing=deepcopy(snapshot);missing['coverage']['start']='2025-08-10'
    short=compute(missing,issued_at=issued)
    assert not short['evidence_context']['forecasts'] and len(short['worker_errors'])==2
    for name,flags in [('sensor_failure',{'sensor':False}),('fire',{'fire':False})]:
        off=compute(snapshot,issued_at=issued,**flags)
        assert off['evidence_context']['workers'][name]['status']=='unavailable'
        assert all(r['worker']!=name for r in off['evidence_context']['forecasts'])
    sys.path.insert(0,str(root))
    from ml.incident_scenarios.evidence import combine_evidence
    options=json.loads((root/'examples/actual_inputs.json').read_text())['combine_options']
    raw=json.loads((root/'examples/actual_three_model_replay.json').read_text())
    for mutation in ('version','nan','infinity','cutoff','duplicate'):
        sensor=deepcopy(raw['sensor_failure_output']);r=sensor['predictions'][0]
        if mutation=='version':r['model_version']='invalid'
        if mutation=='nan':r['score']=float('nan')
        if mutation=='infinity':r['score']=float('inf')
        if mutation=='cutoff':sensor['as_of_date']='2025-08-14'
        if mutation=='duplicate':sensor['predictions'].append(deepcopy(r))
        result=combine_evidence(json.loads((root/'examples/gas_output.json').read_text()),
            sensor,raw['fire_output'],**options)
        assert result['evidence_context']['workers']['sensor_failure']['status']=='invalid'
        assert result['evidence_context']['workers']['fire']['status']=='available'
        assert result['gas']==raw['gas']
    result={'status':'PASS','scope':'real frozen inference on 810 synthetic raw observations; not incident accuracy',
        'sensor_forecasts':2,'fire_forecasts':1,'score_parity_supplier':True,'row_order_invariant':True,
        'future_observations_excluded':True,'insufficient_history_unavailable':True,
        'independent_flags':True,'invalid_worker_isolated':True,'gas_unchanged':True,
        'daily_float_transport_lossless':True,
        'elapsed_seconds':round(time.monotonic()-started,2),'peak_rss_mib':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,1)}
    output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=True)
    (output/'runtime-acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
    (output/'combined_actual_numeric.json').write_text(json.dumps(actual,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    (output/'numeric-snapshot.json').write_text(json.dumps(snapshot,ensure_ascii=False),encoding='utf8')
    print(json.dumps(result))


if __name__=='__main__':main()
