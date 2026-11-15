"""Synthetic publication/security regressions. No live database access."""
from types import SimpleNamespace
from pathlib import Path
import importlib.util
import base64
import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[2]

@pytest.mark.asyncio
@pytest.mark.parametrize('session_id', ['another-users-session', 'missing-session'])
async def test_chat_rejects_unowned_session_before_context_or_message_access(monkeypatch, session_id):
    from app.advisor import router
    seen = []
    class Query:
        def select(self, columns): return self
        def eq(self, key, value): seen.append((key,value)); return self
        def execute(self): return SimpleNamespace(data=[])
    class DB:
        def table(self, name):
            assert name == 'chat_sessions', 'No context or message access before ownership verification'
            return Query()
    monkeypatch.setattr(router, '_gemini', lambda: object())
    monkeypatch.setattr(router, '_db', DB)
    monkeypatch.setattr(router, '_get_mcp_session', lambda _: None)
    with pytest.raises(HTTPException) as error:
        await router.chat(router.ChatRequest(message='synthetic',session_id=session_id), Request({'type':'http'}), SimpleNamespace(id='current-user'))
    assert error.value.status_code == 404
    assert ('id',session_id) in seen
    assert ('user_id','current-user') in seen

@pytest.mark.asyncio
async def test_evaluation_header_does_not_authenticate_in_normal_mode(monkeypatch):
    from app.auth import middleware
    monkeypatch.setattr(middleware, 'EVAL_MOCKS_ENABLED', False)
    request = Request({'type':'http','headers':[(b'x-eval-user-id',b'another-user')]})
    with pytest.raises(HTTPException) as error:
        await middleware.get_current_user(request, None)
    assert error.value.status_code == 401
    assert 'EVAL_MOCKS=0' in (ROOT/'backend/.env.example').read_text()


def test_publication_guard_flags_credentials_without_reporting_values():
    spec=importlib.util.spec_from_file_location('publication_guard',ROOT/'scripts/check_publication.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    token=b'.'.join([base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b'='),base64.urlsafe_b64encode(json.dumps({'role':'service_role'}).encode()).rstrip(b'='),b'synthetic'])
    assert module.findings('app.py',token)==['Supabase service-role token']
    assert module.findings('backend/.env.local',b'placeholder')==['private environment file']
    assert module.findings('backend/.env.example',b'KEY=')==[]
    assert module.findings('app.py',b'AI' + b'za' + b'x'*35)==['Google API key']
