"""Measured local acceptance profiles; no invented SLA or silent loss of failures."""
import concurrent.futures
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse
import httpx

URL=os.environ.get('BASE_URL','http://127.0.0.1:8080')
USERS=int(os.environ.get('LOAD_USERS','20'))
ROUNDS=int(os.environ.get('LOAD_ROUNDS','3'))
INTERVAL=float(os.environ.get('LOAD_INTERVAL_SECONDS','0.1'))
PATHS=('/api/v1/map/objects','/api/v1/objects/1/sensors','/api/v1/alarms',
       '/api/v1/events?limit=100','/api/v1/requests','/api/v1/notifications')

def percentile(values,q):
    return round(sorted(values)[min(len(values)-1,int((len(values)-1)*q))],3) if values else None

def session():
    c=httpx.Client(base_url=URL,timeout=60,trust_env=False)
    try:
        r=c.post('/api/v1/auth/login',json={'username':os.environ['TEST_USERNAME'],'password':os.environ['TEST_PASSWORD']})
        r.raise_for_status(); c.headers['X-CSRF-Token']=r.json()['csrf_token']; return c
    except Exception: c.close(); raise

def traffic(client,mixed=False):
    latencies=[]; errors=0
    def call(method,path,**kwargs):
        nonlocal errors
        started=time.perf_counter()
        try:
            response=client.request(method,path,**kwargs)
            if response.is_error: errors+=1
            return response
        except httpx.HTTPError: errors+=1; return None
        finally:
            latencies.append((time.perf_counter()-started)*1000)
            if INTERVAL: time.sleep(max(0,INTERVAL-(time.perf_counter()-started)))
    for _ in range(ROUNDS):
        for path in PATHS: call('GET',path)
        if mixed:
            r=call('POST','/api/v1/requests',json={'object_id':1,'title':'LOAD TEST — disposable local request'})
            if r is not None and r.status_code==200:
                rid=r.json()['id']
                for state in ('in_progress','completed'):
                    call('PATCH',f'/api/v1/requests/{rid}',json={'status':state})
    return latencies,errors

def profile(name,clients,mixed=False):
    started=time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(clients)) as pool:
        batches=list(pool.map(lambda c:traffic(c,mixed),clients))
    duration=time.perf_counter()-started
    values=[v for batch,_ in batches for v in batch]; errors=sum(n for _,n in batches)
    return {'profile':name,'users':len(clients),'requests':len(values),'errors':errors,
            'error_rate':round(errors/len(values),6) if values else None,
            'duration_seconds':round(duration,3),'rps':round(len(values)/duration,3),
            'p50_ms':percentile(values,.50),'p95_ms':percentile(values,.95),'p99_ms':percentile(values,.99),
            'request_interval_seconds':INTERVAL}

def main():
    if urlparse(URL).hostname not in {'localhost','127.0.0.1','::1'}:
        raise SystemExit('Mixed load writes require an isolated local deployment')
    if USERS<1 or ROUNDS<1 or INTERVAL<0: raise SystemExit('Invalid load profile')
    clients=[]
    try:
        clients.append(session())
        baseline=profile('1_user_baseline',clients)
        clients.extend(session() for _ in range(USERS-1))
        normal=profile('20_users_normal' if USERS==20 else 'concurrent_reads',clients)
        mixed=profile('20_users_mixed' if USERS==20 else 'concurrent_mixed',clients,True)
        report={'base_url':URL,'profiles':[baseline,normal,mixed],
                'passed':all(p['errors']==0 for p in (baseline,normal,mixed)),
                'acceptance_note':'PASS means no HTTP/transport errors; customer SLA not defined.'}
        destination=Path(os.environ.get('LOAD_REPORT','test-results/load.json'))
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))
        if not report['passed']: raise SystemExit(1)
    finally:
        for c in clients:
            try: c.post('/api/v1/auth/logout')
            except httpx.HTTPError: pass
            c.close()
if __name__=='__main__': main()
