"""Version checks protect dispatcher edits without changing legacy REST callers."""
import pytest


def test_stale_edit_never_overwrites_current_request_or_history(login):
    c=login()
    original=c.post('/api/v1/requests',json={'object_id':1,'title':'Before'}).json()
    path=f"/api/v1/requests/{original['id']}"
    first=c.patch(path,json={'title':'First dispatcher','expected_updated_at':original['updated_at']})
    assert first.status_code==200
    stale=c.patch(path,json={'title':'Lost update','expected_updated_at':original['updated_at']})
    assert stale.status_code==409
    assert c.get('/api/v1/requests').json()[0]['title']=='First dispatcher'
    history=c.get(path+'/history').json()
    assert len(history)==2 and history[-1]['changed_fields']==['title']
    fresh=c.patch(path,json={'status':'in_progress','expected_updated_at':first.json()['updated_at']})
    assert fresh.status_code==200 and fresh.json()['completed_at'] is None


@pytest.mark.parametrize('stamp',[None,'2026-10-16T12:00:00','not-a-date'])
def test_invalid_version_stamp_rejected_without_write(login,stamp):
    c=login()
    row=c.post('/api/v1/requests',json={'object_id':1,'title':'Version'}).json()
    assert c.patch(f"/api/v1/requests/{row['id']}",json={'title':'Wrong','expected_updated_at':stamp}).status_code==422
    assert c.get('/api/v1/requests').json()[0]['title']=='Version'


def test_two_simultaneous_dispatcher_edits_have_one_winner(login):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    c=login()
    original=c.post('/api/v1/requests',json={'object_id':1,'title':'Concurrent'}).json()
    barrier=Barrier(2)
    def edit(title):
        barrier.wait(timeout=10)
        return c.patch(f"/api/v1/requests/{original['id']}",json={'title':title,'expected_updated_at':original['updated_at']})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(edit,['Dispatcher A','Dispatcher B']))
    assert sorted(r.status_code for r in results)==[200,409]
    winner=next(r.json()['title'] for r in results if r.status_code==200)
    assert c.get('/api/v1/requests').json()[0]['title']==winner
    assert len(c.get(f"/api/v1/requests/{original['id']}/history").json())==2
