"""Destructive fault injection ONLY into the dedicated synthetic local import QA.

Terminates the owned QA web process/transaction, never a Railway service or DB.
"""
import asyncio
import csv
import json
import os
from pathlib import Path
import zipfile
import httpx
import import_load as qa

BASE='http://127.0.0.1:18094'


def generated():
    return int(qa.sql('SELECT count(*) FROM events_journal WHERE "ид_события">=1000000000000'))


def clean():
    assert qa.sql('SELECT current_database()')==qa.DATABASE
    qa.sql('DELETE FROM events_journal WHERE "ид_события">=1000000000000; DELETE FROM data_imports;')


async def send(client,path):
    with path.open('rb') as f:return await client.post('/api/v1/imports/events',files={'file':(path.name,f)},timeout=125)


async def main():
    qa.verify_local_target(BASE)
    root=Path(os.environ['IMPORT_LOAD_WORK_DIR']);root.mkdir(exist_ok=True,parents=True)
    output=Path(os.environ['IMPORT_LOAD_OUTPUT']);output.mkdir(exist_ok=True,parents=True)
    checks=[]
    def record(name,**details):checks.append({'name':name,'status':'PASS',**details});print('PASS '+name,flush=True)
    async with httpx.AsyncClient(base_url=BASE,timeout=125) as c:
        login=await c.post('/api/v1/auth/login',json={'username':os.environ['TEST_USERNAME'],'password':os.environ['TEST_PASSWORD']});login.raise_for_status();c.headers['X-CSRF-Token']=login.json()['csrf_token']
        for fmt in ['csv','xlsx']:
            clean();path=root/('invalid-last.'+fmt);qa.fixture(path,5000,100,invalid=True)
            r=await send(c,path);assert r.status_code==400 and generated()==0
            assert qa.sql('SELECT status FROM data_imports')=='failed'
            record('invalid final row rolls back earlier batches '+fmt,rows=5000,http=400,committed=0)
        clean();a=root/'overlap-forward.csv';b=root/'overlap-reverse.csv';qa.fixture(a,8000,101)
        with a.open(encoding='utf8',newline='') as stream:rows=list(csv.reader(stream))
        with b.open('w',encoding='utf8',newline='') as stream:csv.writer(stream).writerows([rows[0],*reversed(rows[1:]),rows[1]])
        before=int(qa.sql("SELECT deadlocks FROM pg_stat_database WHERE datname='ldt_import_load_qa'"))
        responses=await asyncio.gather(send(c,a),send(c,b));initial=[r.status_code for r in responses]
        for p,r in zip([a,b],responses):
            if r.status_code in (409,429):r=await send(c,p)
            assert r.status_code==200
        assert generated()==8000
        assert (await send(c,a)).json()['already_imported']
        after=int(qa.sql("SELECT deadlocks FROM pg_stat_database WHERE datname='ldt_import_load_qa'"))
        record('opposite row order, distinct file hashes and duplicate rows are safe',initial_statuses=initial,committed=8000,postgres_deadlocks_recovered=after-before)
        # Stop an active PostgreSQL INSERT while it waits on an owned QA-only lock.
        clean();path=root/'cancel.csv';qa.fixture(path,10000,102)
        qa.docker('exec','-d','-e','PGAPPNAME=import-load-blocker',qa.DB,'psql','-U','import_qa','-d',qa.DATABASE,
            '-c','BEGIN; LOCK TABLE events_journal IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(30); ROLLBACK;')
        for _ in range(30):
            blocker=qa.sql("SELECT pid FROM pg_stat_activity WHERE application_name='import-load-blocker' AND pid<>pg_backend_pid() LIMIT 1")
            if blocker:break
            await asyncio.sleep(.1)
        assert blocker
        task=asyncio.create_task(send(c,path));pid=''
        for _ in range(80):
            pid=await asyncio.to_thread(qa.sql,"SELECT pid FROM pg_stat_activity WHERE datname='ldt_import_load_qa' AND pid<>pg_backend_pid() AND query LIKE 'INSERT INTO events_journal%' AND state='active' LIMIT 1")
            if pid:break
            await asyncio.sleep(.1)
        assert pid
        assert qa.sql(f'SELECT pg_cancel_backend({int(pid)})')=='t'
        qa.sql(f'SELECT pg_terminate_backend({int(blocker)})')
        r=await task;assert r.status_code==408 and generated()==0
        assert qa.sql('SELECT status FROM data_imports')=='failed'
        retry=await send(c,path);assert retry.status_code==200 and generated()==10000
        record('cancelled PostgreSQL transaction returns 408, rolls back and retries',http=408,committed_after_retry=10000)
        # Kill the owned web only after an INSERT acquired a transaction ID and
        # returned to Python while the transaction is still uncommitted.
        clean();path=root/'process-loss.csv';qa.fixture(path,20000,103)
        task=asyncio.create_task(send(c,path));pid=''
        for _ in range(100):
            pid=await asyncio.to_thread(qa.sql,"SELECT pid FROM pg_stat_activity WHERE datname='ldt_import_load_qa' AND backend_xid IS NOT NULL AND state='idle in transaction' AND (query LIKE 'INSERT INTO events_journal%' OR query LIKE 'SELECT set_config%') LIMIT 1")
            if pid:break
            await asyncio.sleep(.05)
        assert pid,'Did not observe the required uncommitted INSERT; do not claim fault PASS'
        qa.docker('kill','--signal=KILL',qa.WEB)
        try:await task
        except httpx.HTTPError:pass
        await asyncio.sleep(.5);assert generated()==0
        interrupted=qa.sql('SELECT status FROM data_imports');assert interrupted=='processing'
        qa.docker('start',qa.WEB);await qa.wait_ready(BASE)
        retry=await send(c,path);assert retry.status_code==200 and generated()==20000
        assert qa.sql('SELECT status FROM data_imports')=='completed'
        record('process loss after uncommitted INSERT preserves atomicity and releases locks',before_retry=interrupted,after_retry='completed',committed_after_retry=20000)
        clean()
        # Abort a partial multipart body before nginx forwards it to the API.
        reader,writer=await asyncio.open_connection('127.0.0.1',18094)
        cookie='; '.join(k+'='+v for k,v in c.cookies.items())
        headers='POST /api/v1/imports/events HTTP/1.1\r\nHost: localhost\r\nCookie: '+cookie+'\r\nX-CSRF-Token: '+c.headers['X-CSRF-Token']+'\r\nContent-Type: multipart/form-data; boundary=qa\r\nContent-Length: 100000\r\n\r\n'
        writer.write(headers.encode()+b'--qa\r\nContent-Disposition: form-data; name="file"; filename="partial.csv"\r\n\r\npartial');await writer.drain();writer.close();await writer.wait_closed();await asyncio.sleep(.5)
        assert qa.sql('SELECT count(*) FROM data_imports')=='0' and generated()==0
        assert (await c.get('/ready')).status_code==200
        record('aborted multipart upload creates no registry row or observations')
        clean();path=root/'oversized-uncompressed.xlsx'
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('large.xml',b'x'*(64*1024*1024+1))
        r=await send(c,path);assert r.status_code==400 and generated()==0
        record('64MiB uncompressed workbook limit rejects compressed bomb before decode',compressed_bytes=path.stat().st_size,uncompressed_bytes=64*1024*1024+1,http=400)
        assert (await c.get('/health')).status_code==200 and (await c.get('/ready')).status_code==200
        await c.post('/api/v1/auth/logout')
    (output/'faults.json').write_text(json.dumps({'status':'PASS','scope':'only new local synthetic QA database; fault windows excluded from normal-load availability','checks':checks},indent=2)+'\n')


if __name__=='__main__':asyncio.run(main())
