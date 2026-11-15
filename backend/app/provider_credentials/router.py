"""Write-only secret API. Parse manually to prevent validation body disclosure."""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from app.auth.middleware import get_current_user
from app.config import settings
from app.db import get_admin_db
from .crypto import PROVIDERS, CredentialError, keyring, unseal
from .store import metadata, save_key, delete_key, row, record_validation

router=APIRouter(prefix='/profile/ai-providers', tags=['AI providers'])
def database(): return get_admin_db()

def check_provider(provider):
    if provider not in PROVIDERS: raise HTTPException(404,'Unsupported AI provider')

def fail(exc): raise HTTPException(exc.status,str(exc)) from None

@router.get('')
def list_keys(response: Response, user=Depends(get_current_user), db=Depends(database)):
    response.headers['Cache-Control']='no-store'
    available=True; error=None; rows=[]
    try:
        keyring(); rows=metadata(db,str(user.id))
    except CredentialError as exc: available=False; error=str(exc)
    saved={r['provider']:r for r in rows}
    return {'available':available,'error':error,'providers':[
        {'provider':p,'configured':p in saved,'enabled':p=='gemini' or settings.evidence_advisor_enabled,
         **saved.get(p,{})} for p in PROVIDERS]}

@router.put('/{provider}')
async def put_key(provider: str, request: Request, response: Response, user=Depends(get_current_user), db=Depends(database)):
    check_provider(provider)
    response.headers['Cache-Control']='no-store'
    # Bound the body before JSON parsing; never include it in validation errors.
    body=bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>8192: raise HTTPException(422,'API key request is too large')
    try:
        import json
        data=json.loads(body)
        if not isinstance(data,dict) or set(data)!={'api_key'}: raise ValueError()
        secret=data['api_key']
        if not isinstance(secret,str) or not 8<=len(secret)<=4096 or any(ord(c)<33 or ord(c)>126 for c in secret): raise ValueError()
    except Exception: raise HTTPException(422,'Enter a valid API key without spaces or control characters.') from None
    try: save_key(db,str(user.id),provider,secret)
    except CredentialError as exc: fail(exc)
    return {'saved':True}

async def probe(provider, secret):
    # Fixed endpoints, no redirects, credentials in headers only. No user data.
    url,headers = ('https://generativelanguage.googleapis.com/v1beta/models?pageSize=1', {'x-goog-api-key':secret}) if provider=='gemini' else ('https://openrouter.ai/api/v1/key',{'Authorization':'Bearer '+secret})
    try:
        async with httpx.AsyncClient(timeout=10,follow_redirects=False,trust_env=False) as client:
            result=await client.get(url,headers=headers)
        return result.status_code==200
    except Exception: return False

@router.post('/{provider}/test')
async def test_key(provider: str, response: Response, user=Depends(get_current_user), db=Depends(database)):
    check_provider(provider); response.headers['Cache-Control']='no-store'
    try:
        r=row(db,str(user.id),provider)
        secret=unseal(str(user.id),provider,r['ciphertext'],r['encryption_key_version'])
        valid=await probe(provider,secret)
        record_validation(db,str(user.id),provider,r['revision'],valid)
    except CredentialError as exc: fail(exc)
    return {'valid':valid,'message': 'Authentication succeeded; model access and quota may differ.' if valid else 'Authentication check failed. Check the key, provider access, and connection.'}

@router.delete('/{provider}',status_code=204)
def remove_key(provider: str, user=Depends(get_current_user), db=Depends(database)):
    check_provider(provider)
    try: delete_key(db,str(user.id),provider)
    except CredentialError as exc: fail(exc)
    return Response(status_code=204,headers={'Cache-Control':'no-store'})
