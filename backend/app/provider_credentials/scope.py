"""Explicit request/job credential ownership, propagated through asyncio.to_thread."""
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import inspect
from google import genai
from app.db import get_admin_db
from .crypto import CredentialError
from .store import get_key

@dataclass
class Scope:
    uid: str | None = None
    clients: list = field(default_factory=list)

_current: ContextVar[Scope | None] = ContextVar('provider_credential_scope', default=None)

@asynccontextmanager
async def credential_scope(uid=None):
    state=Scope(str(uid) if uid else None)
    token=_current.set(state)
    try: yield state
    finally:
        for client in state.clients:
            try:
                if hasattr(client,'aio'): await client.aio.aclose()
                client.close()
            except Exception: pass  # Cleanup must not leak SDK exception details.
        _current.reset(token)

def bind_user(uid):
    state=_current.get()
    if state is None: return  # Standalone auth users may not invoke any AI routes.
    if state.uid is not None and state.uid != str(uid): raise CredentialError('AI credential identity mismatch.')
    state.uid=str(uid)

def provider_key(provider):
    state=_current.get()
    if state is None or not state.uid: raise CredentialError('Authenticated AI credential scope required.',401)
    return get_key(get_admin_db(),state.uid,provider)

def safe_error(exc):
    error=CredentialError('AI provider request failed. Check your saved key, model access, and quota in Settings.')
    error.retryable = getattr(exc, 'code', None) in (429, 503) or getattr(exc, 'status_code', None) in (429, 503)
    return error

def credential_guard(provider, expected_key):
    def check():
        if provider_key(provider) != expected_key:
            raise CredentialError('AI key changed. Retry the operation with your new key.')
    return check

async def _safe_stream(stream):
    try:
        async for chunk in stream: yield chunk
    except CredentialError: raise
    except Exception as exc: raise safe_error(exc) from None

class SafeClient:
    """Expose SDK methods, but never expose upstream error bodies or credentials."""
    def __init__(self,wrapped,check=None): self._wrapped=wrapped; self._check=check
    def __getattr__(self,name):
        attr=getattr(self._wrapped,name)
        if name in {'aio','models'}: return SafeClient(attr,self._check)
        if not callable(attr): return attr
        if inspect.iscoroutinefunction(attr):
            async def call(*args,**kwargs):
                if self._check: self._check()
                try:
                    result=await attr(*args,**kwargs)
                    return _safe_stream(result) if hasattr(result,'__aiter__') else result
                except CredentialError: raise
                except Exception as exc: raise safe_error(exc) from None
        else:
            def call(*args,**kwargs):
                if self._check: self._check()
                try: return attr(*args,**kwargs)
                except CredentialError: raise
                except Exception as exc: raise safe_error(exc) from None
        return call

def gemini_client(optional=False):
    try:
        key=provider_key('gemini')
        client=genai.Client(api_key=key)
        _current.get().clients.append(client)
        return SafeClient(client,credential_guard('gemini',key))
    except CredentialError:
        if optional: return None
        raise
    except Exception:
        if optional: return None
        raise CredentialError('Could not initialize Gemini. Check AI providers in Settings.') from None

class CredentialScopeMiddleware:
    def __init__(self,app): self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http': return await self.app(scope,receive,send)
        async with credential_scope():
            await self.app(scope,receive,send)
