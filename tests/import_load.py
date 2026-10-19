"""Opt-in local-only CSV/XLSX contention probe. Never use a Railway database.

Creates synthetic files, samples cgroup counters and PostgreSQL connections,
offers simultaneous uploads, then retries explicit backpressure in pairs.
The named web container is restarted between cases to reset its memory peak.
Only generated rows in the dedicated ldt_import_load_qa database are cleaned.
"""
import argparse
import asyncio
from collections import Counter
import csv
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse

import httpx
from openpyxl import Workbook

DOCKER = os.environ.get('IMPORT_LOAD_DOCKER','docker')
WEB, DB = 'ldt-import-load-web', 'ldt-import-load-db'
DATABASE = 'ldt_import_load_qa'
FIELDS = ['ид_события','ид_канала_данных','дата','время','тревожное','значение_датчика']


def docker(*args):
    p=subprocess.run([DOCKER,*args],capture_output=True,text=True,encoding='utf8',timeout=20)
    if p.returncode:raise RuntimeError('Local QA Docker command failed: '+args[0])
    return p.stdout


def sql(query):
    return docker('exec',DB,'psql','-U','import_qa','-d',DATABASE,'-Atc',query).strip()


def verify_local_target(base):
    url=urlparse(base)
    if (os.environ.get('RUN_IMPORT_LOAD')!='true' or url.hostname not in {'127.0.0.1','localhost'}
        or url.scheme!='http' or url.port!=18094):
        raise SystemExit('Explicit opt-in and the owned loopback QA port18094 required; never Railway')
    ports=json.loads(docker('inspect','--format','{{json .NetworkSettings.Ports}}',WEB))
    assert any(x['HostIp']=='127.0.0.1' and x['HostPort']=='18094' for x in ports.get('8080/tcp',[])), 'Target must be the owned QA Docker binding'
    assert sql('SELECT current_database()')==DATABASE


def percentile(values,q):
    if not values:return None
    ordered=sorted(values);return round(ordered[min(len(ordered)-1,int((len(ordered)-1)*q))],2)


def fixture(path,rows,number,invalid=False):
    def values():
        yield FIELDS
        for i in range(rows):
            yield [str(1000000000000+number*1000000+i),'1',
                'invalid' if invalid and i==rows-1 else '2026-10-20','12:00:00','false',str(20+i%10)]
    if path.suffix=='.csv':
        with path.open('w',encoding='utf-8',newline='') as f:csv.writer(f).writerows(values())
    else:
        book=Workbook(write_only=True);sheet=book.create_sheet()
        for row in values():sheet.append(row)
        book.save(path)


def sample():
    result={}
    for name in [WEB,DB]:
        text=docker('exec',name,'sh','-c','cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.peak /sys/fs/cgroup/cpu.stat /sys/fs/cgroup/memory.events /sys/fs/cgroup/memory.stat')
        cpu_at=time.monotonic()
        lines=text.splitlines();cpu=dict(x.split() for x in lines[2:] if len(x.split())==2)
        result[name]={'memory_bytes':int(lines[0]),'peak_bytes':int(lines[1]),'cpu_usec':int(cpu['usage_usec']),
            'cpu_at':cpu_at,'anon_bytes':int(cpu.get('anon',0)),
            'working_set_bytes':max(0,int(lines[0])-int(cpu.get('inactive_file',0))),
            'oom_kill':int(cpu.get('oom_kill',0)),'oom_events':int(cpu.get('oom',0))}
    result['connections']=json.loads(sql("SELECT json_build_object('total',count(*),'target',count(*) FILTER(WHERE datname='ldt_import_load_qa'),'active',count(*) FILTER(WHERE state='active' AND pid<>pg_backend_pid()),'idle_in_transaction',count(*) FILTER(WHERE state='idle in transaction'),'import_slots',(SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND classid=1279546441 AND objsubid=2 AND granted)) FROM pg_stat_activity"))
    result['at']=time.monotonic();return result


async def wait_ready(base):
    async with httpx.AsyncClient(base_url=base,timeout=3) as c:
        for _ in range(40):
            try:
                if (await c.get('/ready')).status_code==200:return
            except httpx.HTTPError:pass
            await asyncio.sleep(.5)
    raise RuntimeError('Isolated QA did not become ready')


async def run_case(args,format,concurrent,mode,number):
    # These are exclusively generated records in a new dedicated database.
    assert sql('SELECT current_database()')==DATABASE
    docker('restart',WEB);await wait_ready(args.base_url)
    sql('DELETE FROM events_journal WHERE "ид_события">=1000000000000; DELETE FROM data_imports;')
    directory=Path(args.work_dir);directory.mkdir(exist_ok=True,parents=True)
    paths=[]
    for i in range(1 if mode=='same' else concurrent):
        suffix=('csv' if i%2==0 else 'xlsx') if format=='mixed' else format
        path=directory/f'import-load-{number}-{i}.{suffix}';fixture(path,args.rows,number*100+i);paths.append(path)
    files=[paths[0] if mode=='same' else paths[i] for i in range(concurrent)]
    samples=[];api=[];stop=asyncio.Event()
    async with httpx.AsyncClient(base_url=args.base_url,timeout=httpx.Timeout(125,connect=5),limits=httpx.Limits(max_connections=50)) as client:
        login=await client.post('/api/v1/auth/login',json={'username':os.environ['TEST_USERNAME'],'password':os.environ['TEST_PASSWORD']});login.raise_for_status()
        client.headers['X-CSRF-Token']=login.json()['csrf_token']
        async def ordinary():
            while not stop.is_set():
                for path in ['/health','/api/v1/map/objects','/api/v1/imports']:
                    start=time.monotonic()
                    try:r=await client.get(path,timeout=5);status=r.status_code
                    except httpx.HTTPError as exc:status=type(exc).__name__
                    api.append({'path':path,'status':status,'ms':(time.monotonic()-start)*1000})
                await asyncio.sleep(.3)
        async def monitor():
            while not stop.is_set():
                try:samples.append(await asyncio.to_thread(sample))
                except RuntimeError:pass
                await asyncio.sleep(.5)
        async def upload(path):
            started=time.monotonic()
            try:
                with path.open('rb') as f:r=await client.post('/api/v1/imports/events',files={'file':(path.name,f)})
                try:body=r.json()
                except ValueError:body={}
                detail=body.get('detail') if isinstance(body.get('detail'),dict) else {}
                return {'file':path.name,'status':r.status_code,'seconds':round(time.monotonic()-started,3),
                    'already_imported':body.get('already_imported'),'inserted':body.get('inserted_rows'),
                    'code':body.get('code') or detail.get('code'),'retry_after':r.headers.get('retry-after')}
            except httpx.HTTPError as exc:
                return {'file':path.name,'status':type(exc).__name__,'seconds':round(time.monotonic()-started,3)}
        background=[asyncio.create_task(ordinary()),asyncio.create_task(monitor())]
        started=time.monotonic();first=await asyncio.gather(*(upload(p) for p in files));retries=[]
        # Expected 429/409 are backpressure, not successful imports. Prove safe retries.
        pending=[files[i] for i,r in enumerate(first) if r['status'] in (409,429)]
        for offset in range(0,len(pending),2):
            retries.extend(await asyncio.gather(*(upload(p) for p in pending[offset:offset+2])))
        elapsed=time.monotonic()-started;stop.set();await asyncio.gather(*background)
        await client.post('/api/v1/auth/logout')
    try:end=await asyncio.to_thread(sample);samples.append(end)
    except RuntimeError:
        if not samples:raise
        end=samples[-1]
    memory={};cpu={}
    for name in [WEB,DB]:
        memory[name]={'sampled_peak_mib':round(max(s[name]['memory_bytes'] for s in samples)/1048576,2),
            'kernel_peak_mib':round(end[name]['peak_bytes']/1048576,2),
            'working_set_peak_mib':round(max(s[name]['working_set_bytes'] for s in samples)/1048576,2),
            'anon_peak_mib':round(max(s[name]['anon_bytes'] for s in samples)/1048576,2),
            'oom_kill':end[name]['oom_kill'],'oom_events':end[name]['oom_events']}
        rates=[(b[name]['cpu_usec']-a[name]['cpu_usec'])/1e6/(b[name]['cpu_at']-a[name]['cpu_at'])*100 for a,b in zip(samples,samples[1:]) if b[name]['cpu_at']>a[name]['cpu_at']]
        cpu[name]={'sampled_max_pct_one_core':round(max(rates),2) if rates else None,'allocation_vcpu':2}
        interval=end[name]['cpu_at']-samples[0][name]['cpu_at']
        cpu[name]['interval_average_pct_one_core']=round((end[name]['cpu_usec']-samples[0][name]['cpu_usec'])/1e6/interval*100,2) if interval>0 else None
    expected=args.rows*(1 if mode=='same' else concurrent)
    actual=int(sql('SELECT count(*) FROM events_journal WHERE "ид_события">=1000000000000'))
    counts=dict(Counter(str(r['status']) for r in first));unexpected=sum(r['status'] not in (200,409,429) for r in first)
    result={'format':format,'offered_concurrent':concurrent,'mode':mode,'rows_per_file':args.rows,
        'file_bytes':[p.stat().st_size for p in paths],'first_attempts':first,'first_statuses':counts,
        'unexpected_error_rate':unexpected/concurrent,'retries':retries,'wall_seconds':round(elapsed,2),
        'processing_seconds':{'p50':percentile([r['seconds'] for r in first],.5),'p95':percentile([r['seconds'] for r in first],.95),'max':max(r['seconds'] for r in first)},
        'memory':memory,'cpu':cpu,'connections_peak':{k:max(s['connections'][k] for s in samples) for k in end['connections']},
        'ordinary_api':{'requests':len(api),'failures':sum(r['status']!=200 for r in api),'statuses':dict(Counter(str(r['status']) for r in api)),
            'per_path':{p:{'requests':sum(r['path']==p for r in api),'failures':sum(r['path']==p and r['status']!=200 for r in api)} for p in {r['path'] for r in api}},
            'p50_ms':percentile([r['ms'] for r in api],.5),'p95_ms':percentile([r['ms'] for r in api],.95),'max_ms':round(max(r['ms'] for r in api),2)},
        'expected_generated_rows':expected,'actual_generated_rows':actual,'rows_match':actual==expected,
        'monitor_samples':len(samples),'oom_killed':json.loads(docker('inspect','--format','{{json .State.OOMKilled}}',WEB))}
    accepted=[r['seconds'] for r in first+retries if r['status']==200 and not r.get('already_imported')]
    result['accepted_processing_seconds']={'p50':percentile(accepted,.5),'p95':percentile(accepted,.95),'max':max(accepted) if accepted else None}
    out=Path(args.output);out.mkdir(exist_ok=True,parents=True);(out/f'{format}-{concurrent}-{mode}.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/f'{format}-{concurrent}-{mode}-samples.json').write_text(json.dumps(samples,indent=2)+'\n')
    print(json.dumps({'case':f'{format}/{concurrent}/{mode}','statuses':counts,'api_errors':result['ordinary_api']['failures'],
        'RAM_MiB':memory[WEB]['kernel_peak_mib'],'connections':result['connections_peak']['target'],'rows_match':result['rows_match'],'seconds':result['wall_seconds']}),flush=True)
    return result


async def main(args):
    verify_local_target(args.base_url)
    results=[];number=1
    for format in args.formats.split(','):
        for n in map(int,args.users.split(',')):
            for mode in args.modes.split(','):
                results.append(await run_case(args,format,n,mode,number));number+=1
    Path(args.output,'summary.json').write_text(json.dumps(results,indent=2)+'\n')
    if args.require_pass and not all(
        r['rows_match'] and not r['oom_killed'] and r['ordinary_api']['failures']==0
        and r['connections_peak']['import_slots']<=2
        and all(x['status'] in (200,409,429) for x in r['first_attempts']+r['retries'])
        and all(m.get('oom_kill',0)==0 and m.get('oom_events',0)==0 for m in r['memory'].values())
        for r in results
    ):
        raise SystemExit('Import acceptance failed; inspect the saved summary')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:18094');p.add_argument('--rows',type=int,default=10000)
    p.add_argument('--users',default='5,10,20');p.add_argument('--formats',default='csv,xlsx');p.add_argument('--modes',default='different,same')
    p.add_argument('--require-pass',action='store_true',help='Fail after saving evidence if availability, atomicity, OOM or backpressure checks fail')
    p.add_argument('--output',required=True);p.add_argument('--work-dir',required=True);asyncio.run(main(p.parse_args()))
