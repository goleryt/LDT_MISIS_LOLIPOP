"""LDAPS transport contract; real AD remains an external dependency."""
import ssl
from types import SimpleNamespace
from app.core import ldap_adapter
from app.core.config import get_settings

def test_read_only_tls_verified_escaped_search_and_no_fallback(monkeypatch):
    s=get_settings()
    for key,value in {'ldap_host':'directory.test','ldap_base_dn':'dc=test','ldap_bind_dn':'cn=reader',
                      'ldap_bind_password':'test-fixture-only','ldap_role_groups':{'cn=dispatchers':'dispatcher'}}.items():
        monkeypatch.setattr(s,key,value)
    options=[]; searches=[]
    entry=SimpleNamespace(memberOf=SimpleNamespace(values=['cn=dispatchers']),entry_dn='cn=test-user')
    service=SimpleNamespace(entries=[entry],search=lambda *a,**kw:searches.append((a,kw)),unbind=lambda:None)
    user=SimpleNamespace(bind=lambda:True,unbind=lambda:None)
    def connection(*args,**kwargs):
        options.append(kwargs)
        return service if len(options)==1 else user
    tls_options={}
    monkeypatch.setattr(ldap_adapter,'Tls',lambda **kw:tls_options.update(kw))
    monkeypatch.setattr(ldap_adapter,'Server',lambda *a,**kw:SimpleNamespace(**kw))
    monkeypatch.setattr(ldap_adapter,'Connection',connection)
    assert ldap_adapter.authenticate_ldap('a*)(uid=*)','test-fixture-password')=='dispatcher'
    assert tls_options['validate']==ssl.CERT_REQUIRED
    assert all(x['read_only'] and x['auto_referrals'] is False for x in options)
    assert '\\2a' in searches[0][0][1] and searches[0][1]['size_limit']==2
    assert ldap_adapter.authenticate_ldap('user','') is None

def test_unavailable_directory_does_not_fall_back_to_local_password(client, monkeypatch):
    from conftest import PASSWORD
    monkeypatch.setattr(get_settings(),'auth_provider','ldap')
    def unavailable(*args): raise ConnectionError('Do not expose directory details')
    monkeypatch.setattr(ldap_adapter,'authenticate_ldap',unavailable)
    response=client.post('/api/v1/auth/login',json={'username':'dispatcher','password':PASSWORD})
    assert response.status_code==503
    assert 'directory details' not in response.text
