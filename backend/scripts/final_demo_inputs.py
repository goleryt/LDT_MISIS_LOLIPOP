"""Original 29 September demo inputs, reproduced without retuning or inference.

Restores the exact fixed synthetic generator used by demo_synthetic_ml.py in
the original demo deployment. Scores are never part of this input generator.
"""
import csv
from datetime import date, timedelta
import hashlib
from pathlib import Path

DAY = date(2026,9,28)
OBJECT = 900000001
CHANNELS = (900000001,900000002,900000003)


def export_gas_inputs(directory):
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    cat=root/'synthetic-demo-catalogue.csv'
    journal=root/'synthetic-demo-journal-20260928.csv'
    # Refuse to overwrite an unknown source file. Repeat runs compare bytes.
    from io import StringIO
    catalogue=StringIO(newline='');writer=csv.writer(catalogue)
    writer.writerow(['ид_канала_данных','ид_объект','тип_датчика','тип_инж_системы'])
    for channel in CHANNELS:writer.writerow([channel,OBJECT,'Газовый датчик','Газ'])
    events=StringIO(newline='');writer=csv.writer(events)
    writer.writerow(['ид_события','ид_канала_данных','дата','время','тревожное','значение_датчика'])
    for i,channel in enumerate(CHANNELS):
        for n in range(430):
            day=DAY-timedelta(days=429-n)
            for hour in (0,8,16):
                value=(0.2+n%11*0.01) if i==0 else (0.25+0.65*max(0,n-400)/29 if i==1 else 0.3+(0.85 if n%31<3 else 0))
                writer.writerow([900000000000+i*10000+n*24+hour,channel,day.isoformat(),f'{hour:02}:00:00',str(value>=1).lower(),f'{value:.3f}'])
    files={cat:catalogue.getvalue().encode('utf8'),journal:events.getvalue().encode('utf8')}
    for path,raw in files.items():
        if path.exists() and path.read_bytes()!=raw:raise RuntimeError('UNKNOWN_DEMO_INPUT_FILE_COLLISION')
    for path,raw in files.items():path.write_bytes(raw)
    return {'dataset_version':'gas-synthetic-demo-20260928-v1','synthetic':True,'as_of_date':str(DAY),
        'object_id':OBJECT,'channel_ids':list(CHANNELS),'observed_days':430,'rows':3870,
        'coverage_start':str(DAY-timedelta(days=429)),'coverage_end_inclusive':str(DAY),
        'source':'Original deterministic synthetic demo inputs of 29 September; unchanged generator',
        'files':{path.name:hashlib.sha256(raw).hexdigest() for path,raw in files.items()},
        'new_inference_performed':False,'scores_generated':False}
