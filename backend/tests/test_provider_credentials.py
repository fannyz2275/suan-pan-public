import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.config import settings
from app.provider_credentials.crypto import seal, unseal, CredentialError
from app.provider_credentials.store import save_key, get_key, delete_key, metadata, record_validation

UID='00000000-0000-4000-8000-000000000001'
OTHER='00000000-0000-4000-8000-000000000002'
SECRET='synthetic-provider-key-never-real-1234'

class DB:
    def __init__(self): self.rows=[]
    def table(self, name):
        assert name=='user_provider_credentials'
        return Query(self)
class Query:
    def __init__(self, db): self.db=db; self.filters={}; self.op='select'; self.body=None
    def order(self,*args): return self
    def range(self,*args): return self
    def select(self,*args): return self
    def eq(self,k,v): self.filters[k]=v; return self
    def upsert(self,body,**kwargs): self.op='upsert'; self.body=body; return self
    def update(self,body): self.op='update'; self.body=body; return self
    def delete(self): self.op='delete'; return self
    def execute(self):
        rows=[r for r in self.db.rows if all(r.get(k)==v for k,v in self.filters.items())]
        if self.op=='upsert':
            self.db.rows[:]=[r for r in self.db.rows if (r['user_id'],r['provider']) != (self.body['user_id'],self.body['provider'])]
            self.db.rows.append(deepcopy(self.body))
        if self.op=='delete': self.db.rows[:]=[r for r in self.db.rows if r not in rows]
        if self.op=='update':
            for r in rows: r.update(deepcopy(self.body))
        return SimpleNamespace(data=deepcopy(rows))

@pytest.fixture(autouse=True)
def encryption(monkeypatch):
    monkeypatch.setattr(settings,'provider_keys_encryption_keys',json.dumps({'v1':Fernet.generate_key().decode()}))
    monkeypatch.setattr(settings,'provider_keys_active_version','v1')


def test_bound_encryption_and_tampering():
    ciphertext,version=seal(UID,'gemini',SECRET)
    assert SECRET not in ciphertext
    assert unseal(UID,'gemini',ciphertext,version)==SECRET
    for uid,provider,token in [(OTHER,'gemini',ciphertext),(UID,'openrouter',ciphertext),(UID,'gemini',ciphertext[:-3]+'abc')]:
        with pytest.raises(CredentialError): unseal(uid,provider,token,version)


def test_crud_isolation_and_safe_metadata():
    db=DB(); save_key(db,UID,'gemini',SECRET)
    assert SECRET not in repr(db.rows)
    assert get_key(db,UID,'gemini')==SECRET
    with pytest.raises(CredentialError): get_key(db,OTHER,'gemini')
    assert SECRET not in repr(metadata(db,UID))
    delete_key(db,OTHER,'gemini')
    assert get_key(db,UID,'gemini')==SECRET
    delete_key(db,UID,'gemini')
    with pytest.raises(CredentialError): get_key(db,UID,'gemini')


def test_rotation_and_missing_config(monkeypatch):
    db=DB(); save_key(db,UID,'gemini',SECRET)
    keys=json.loads(settings.provider_keys_encryption_keys); keys['v2']=Fernet.generate_key().decode()
    monkeypatch.setattr(settings,'provider_keys_encryption_keys',json.dumps(keys))
    monkeypatch.setattr(settings,'provider_keys_active_version','v2')
    assert get_key(db,UID,'gemini')==SECRET
    save_key(db,UID,'gemini',get_key(db,UID,'gemini'))
    assert db.rows[0]['encryption_key_version']=='v2'
    monkeypatch.setattr(settings,'provider_keys_encryption_keys','')
    with pytest.raises(CredentialError): get_key(db,UID,'gemini')


def test_old_validation_cannot_mark_replacement_valid():
    db=DB(); save_key(db,UID,'gemini',SECRET)
    revision=db.rows[0]['revision']
    save_key(db,UID,'gemini','replacement-synthetic-key')
    record_validation(db,UID,'gemini',revision,True)
    assert db.rows[0]['validation_status']=='untested'


def client_for(db,uid=UID):
    from app.provider_credentials import router as routes
    from app.auth.middleware import get_current_user
    app=FastAPI(); app.include_router(routes.router)
    app.dependency_overrides[routes.get_current_user]=lambda: SimpleNamespace(id=uid)
    app.dependency_overrides[routes.database]=lambda: db
    return TestClient(app)


def test_routes_never_return_secrets_and_validate_without_echo():
    db=DB(); c=client_for(db)
    for payload in [{'api_key':SECRET,'unexpected':SECRET},{'api_key':SECRET+'\n'}, {'api_key':''}]:
        r=c.put('/profile/ai-providers/gemini',json=payload)
        assert r.status_code==422
        assert SECRET not in r.text
    assert c.put('/profile/ai-providers/unknown',json={'api_key':SECRET}).status_code==404
    assert c.put('/profile/ai-providers/gemini',json={'api_key':SECRET}).status_code==200
    r=c.get('/profile/ai-providers'); assert SECRET not in r.text and 'ciphertext' not in r.text
    assert r.headers['cache-control']=='no-store'
    assert not client_for(db,OTHER).get('/profile/ai-providers').json()['providers'][0]['configured']
    assert c.delete('/profile/ai-providers/gemini').status_code==204


def test_missing_encryption_is_actionable(monkeypatch):
    monkeypatch.setattr(settings,'provider_keys_encryption_keys','')
    c=client_for(DB())
    assert c.get('/profile/ai-providers').json()['available'] is False
    r=c.put('/profile/ai-providers/gemini',json={'api_key':SECRET})
    assert r.status_code==503 and SECRET not in r.text

@pytest.mark.asyncio
async def test_request_scopes_isolate_threads_and_close_clients(monkeypatch):
    import asyncio
    from app.provider_credentials import scope
    db=DB(); save_key(db,UID,'gemini',SECRET); save_key(db,OTHER,'gemini','other-synthetic-key')
    monkeypatch.setattr(scope,'get_admin_db',lambda:db)
    clients=[]
    class Client:
        def __init__(self,api_key): self.key=api_key; self.closed=False; clients.append(self)
        def close(self): self.closed=True
    monkeypatch.setattr(scope.genai,'Client',Client)
    async def run(uid):
        async with scope.credential_scope(uid):
            await asyncio.sleep(0)
            return await asyncio.to_thread(scope.provider_key,'gemini')
    assert await asyncio.gather(run(UID),run(OTHER))==[SECRET,'other-synthetic-key']
    async with scope.credential_scope(UID): scope.gemini_client()
    assert clients[0].closed
    with pytest.raises(CredentialError): scope.provider_key('gemini')

@pytest.mark.asyncio
async def test_client_errors_do_not_expose_provider_payloads(monkeypatch):
    from app.provider_credentials.scope import SafeClient
    class Models:
        def generate_content(self,**kwargs): raise ValueError(SECRET)
    client=SafeClient(SimpleNamespace(models=Models()))
    with pytest.raises(CredentialError) as e: client.models.generate_content(contents='hello')
    assert SECRET not in str(e.value)

@pytest.mark.asyncio
async def test_call_sites_use_current_user_keys(monkeypatch):
    import importlib
    from app.provider_credentials import scope
    db=DB(); save_key(db,UID,'gemini',SECRET); save_key(db,OTHER,'gemini','other-synthetic-key')
    monkeypatch.setattr(scope,'get_admin_db',lambda:db)
    calls=[]
    class Models:
        def generate_content(self,**kwargs): return SimpleNamespace(text='[]')
    class Client:
        def __init__(self,api_key): calls.append(api_key); self.models=Models()
        def close(self): pass
    monkeypatch.setattr(scope.genai,'Client',Client)
    for uid,secret in [(UID,SECRET),(OTHER,'other-synthetic-key')]:
        async with scope.credential_scope(uid):
            for module,method,args in [
                ('app.advisor.router','_gemini',()),('app.engine.router','_gemini_client',()),
                ('app.imports.parser','_call_gemini',('no private data',)),
                ('app.portfolio.statement_parser','parse_investment_statement',('synthetic',)),
                ('app.engine.recurring.llm','_call_gemini',('synthetic',)),
            ]:
                before=len(calls)
                getattr(importlib.import_module(module),method)(*args)
                assert calls[before:]==[secret]


def test_auth_required_without_override():
    from app.provider_credentials.router import router
    app=FastAPI(); app.include_router(router)
    assert TestClient(app).get('/profile/ai-providers').status_code==401


def test_test_route_sanitized_and_saved_status(monkeypatch):
    from app.provider_credentials import router as routes
    db=DB(); save_key(db,UID,'gemini',SECRET)
    async def probe(provider,key):
        assert key==SECRET
        return False
    monkeypatch.setattr(routes,'probe',probe)
    r=client_for(db).post('/profile/ai-providers/gemini/test')
    assert r.status_code==200 and not r.json()['valid']
    assert SECRET not in r.text
    assert db.rows[0]['validation_status']=='failed'

@pytest.mark.asyncio
async def test_delete_during_background_call_blocks_next_transport(monkeypatch):
    import asyncio
    from app.provider_credentials import scope
    db=DB(); save_key(db,UID,'gemini',SECRET)
    monkeypatch.setattr(scope,'get_admin_db',lambda:db)
    started=asyncio.Event(); release=asyncio.Event(); calls=[]
    class Models:
        async def generate_content(self,**kw):
            calls.append(kw); started.set(); await release.wait()
            return SimpleNamespace(text='{}')
    class Client:
        def __init__(self,api_key): self.aio=SimpleNamespace(models=Models(),aclose=self.aclose)
        async def aclose(self): pass
        def close(self): pass
    monkeypatch.setattr(scope.genai,'Client',Client)
    async with scope.credential_scope(UID):
        c=scope.gemini_client()
        job=asyncio.create_task(c.aio.models.generate_content(contents='synthetic'))
        await started.wait(); delete_key(db,UID,'gemini'); release.set(); await job
        with pytest.raises(CredentialError): await c.aio.models.generate_content(contents='next job stage')
    assert len(calls)==1

@pytest.mark.asyncio
async def test_sanitized_transient_status_preserves_retry():
    from app.provider_credentials.scope import SafeClient
    from app.advisor.resilience import classify_gemini_error
    class UpstreamError(Exception): code=503
    class Models:
        async def generate_content(self,**kw): raise UpstreamError(SECRET)
    client=SafeClient(SimpleNamespace(models=Models()))
    with pytest.raises(CredentialError) as e: await client.models.generate_content()
    assert classify_gemini_error(e.value)
    assert SECRET not in str(e.value)

def test_operator_rotation_preserves_secret_and_validation(monkeypatch):
    from app.provider_credentials.rotate import rotate
    db=DB(); save_key(db,UID,'gemini',SECRET)
    record_validation(db,UID,'gemini',db.rows[0]['revision'],True)
    keys=json.loads(settings.provider_keys_encryption_keys);keys['v2']=Fernet.generate_key().decode()
    monkeypatch.setattr(settings,'provider_keys_encryption_keys',json.dumps(keys))
    monkeypatch.setattr(settings,'provider_keys_active_version','v2')
    assert rotate(db)==1
    monkeypatch.setattr(settings,'provider_keys_encryption_keys',json.dumps({'v2':keys['v2']}))
    assert get_key(db,UID,'gemini')==SECRET
    assert db.rows[0]['validation_status']=='valid'
    assert rotate(db)==0

@pytest.mark.asyncio
async def test_background_tick_scopes_two_users(monkeypatch):
    from app.notes import extraction, compaction
    from app.provider_credentials import scope
    keys=DB();save_key(keys,UID,'gemini',SECRET);save_key(keys,OTHER,'gemini','other-synthetic-key')
    monkeypatch.setattr(scope,'get_admin_db',lambda:keys)
    transports=[]
    class Client:
        def __init__(self,api_key): self.aio=SimpleNamespace(models=self,aclose=self.aclose);self.key=api_key
        async def generate_content(self,**kwargs): transports.append(self.key);return SimpleNamespace(text='{}')
        async def aclose(self): pass
        def close(self): pass
    monkeypatch.setattr(scope.genai,'Client',Client)
    class JobDB:
        def rpc(self,name,args):
            return SimpleNamespace(execute=lambda:SimpleNamespace(data=[{'user_id':UID},{'user_id':OTHER}] if name=='notes_eligible_users_for_extraction' else True))
        def table(self,name): return self
        def select(self,*args): return self
        def eq(self,*args): return self
        def limit(self,*args): return self
        def update(self,*args): return self
        def execute(self): return SimpleNamespace(data=[])
    async def extract(**kwargs):
        await kwargs['gemini'].aio.models.generate_content(contents='synthetic');return 1
    async def merge(**kwargs): await kwargs['gemini'].aio.models.generate_content(contents='synthetic merge')
    monkeypatch.setattr(extraction,'extract_for_user',extract)
    monkeypatch.setattr(compaction,'merge_preferences_for_user',merge)
    assert await extraction.tick(db_factory=JobDB,gemini=None)==2
    assert transports==[SECRET,SECRET,'other-synthetic-key','other-synthetic-key']

@pytest.mark.asyncio
async def test_openrouter_transport_isolation_and_deletion(monkeypatch):
    import httpx
    from app.advisor.evidence.provider import Provider
    from app.provider_credentials import scope
    db=DB();save_key(db,UID,'openrouter',SECRET);save_key(db,OTHER,'openrouter','other-synthetic-key')
    monkeypatch.setattr(scope,'get_admin_db',lambda:db)
    seen=[]
    def transport(request):
        seen.append(request.headers['Authorization'])
        assert SECRET not in request.content.decode()
        return httpx.Response(200,json={'model':'google/gemini-2.5-flash','choices':[{'message':{'content':'{}'}}]})
    with httpx.Client(transport=httpx.MockTransport(transport)) as http:
        for uid in [UID,OTHER]:
            async with scope.credential_scope(uid):
                key=scope.provider_key('openrouter')
                provider=Provider(key,client=http,credential_check=scope.credential_guard('openrouter',key))
                assert provider.complete('planner',[],max_tokens=10)=={}
                delete_key(db,uid,'openrouter')
                with pytest.raises(CredentialError): provider.complete('planner',[],max_tokens=10)
    assert seen==['Bearer '+SECRET,'Bearer other-synthetic-key']

@pytest.mark.asyncio
@pytest.mark.parametrize('status,retryable',[(503,True),(429,True),(403,False)])
async def test_safe_client_retry_behavior(status,retryable):
    from app.provider_credentials.scope import SafeClient
    from app.advisor.resilience import stream_with_retry, TransientError, classify_gemini_error
    calls=[]
    class Upstream(Exception): code=status
    class Models:
        async def generate_content_stream(self):
            calls.append(1)
            if len(calls)==1: raise Upstream(SECRET)
            return 'success'
    c=SafeClient(SimpleNamespace(models=Models()))
    async def factory():
        try: return await c.models.generate_content_stream()
        except CredentialError as exc:
            if classify_gemini_error(exc): raise TransientError(str(exc)) from None
            raise
    if retryable: assert await stream_with_retry(factory,backoff=(0,))=='success'
    else:
        with pytest.raises(CredentialError): await stream_with_retry(factory,backoff=(0,))
    assert len(calls)==(2 if retryable else 1)

@pytest.mark.asyncio
async def test_chat_without_key_fails_before_database_or_model_calls(monkeypatch):
    from app.advisor import router as chat
    from app.provider_credentials import scope
    from starlette.requests import Request
    monkeypatch.setattr(scope,'get_admin_db',DB)
    def unexpected(): raise AssertionError('Chat must not write history before key preflight')
    monkeypatch.setattr(chat,'_db',unexpected)
    async with scope.credential_scope(UID):
        with pytest.raises(CredentialError,match='Settings'):
            await chat.chat(chat.ChatRequest(message='synthetic'),Request({'type':'http'}),SimpleNamespace(id=UID))
