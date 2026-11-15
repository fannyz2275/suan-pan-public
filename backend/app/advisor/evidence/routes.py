import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.auth.middleware import get_current_user
from app.config import settings
from app.provider_credentials.scope import provider_key, credential_guard
from app.provider_credentials.crypto import CredentialError
from app.db import get_admin_db
from app.advisor.pending import readiness, claim_state
from .data import live_adapter
from .pipeline import run_analysis
from .provider import Provider

router = APIRouter()
logger = logging.getLogger(__name__)


class AnalysisRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    session_id: str | None = None
    month: str | None = Field(default=None, pattern=r'^\d{4}-\d{2}$')


def enabled():
    if not settings.evidence_advisor_enabled:
        raise HTTPException(503, 'Evidence-first analysis is not enabled. Apply migrations before enabling it.')


def owned_session(db, uid, session_id):
    rows = db.table('chat_sessions').select('id').eq('id',session_id).eq('user_id',uid).execute().data
    if not rows: raise HTTPException(404, 'Conversation not found')


def history_for(db, session_id):
    rows = db.table('chat_messages').select('role,content,tool_context').eq('session_id',session_id).order('created_at',desc=True).limit(20).execute().data or []
    return list(reversed(rows))


def analyze(db, uid, body, *, adapter=None, resumed=False):
    sid = body.session_id
    if sid: owned_session(db,uid,sid)
    else: sid = db.table('chat_sessions').insert({'user_id':uid}).execute().data[0]['id']
    history = history_for(db,sid)
    month = body.month
    if month is None:
        month = next((r['tool_context']['analysis_scope']['month'] for r in reversed(history)
                      if (r.get('tool_context') or {}).get('analysis_scope')), None)
    adapter = adapter or live_adapter(db,uid,month)
    scope = adapter.context().get('scope', {})
    if not resumed:
        db.table('chat_messages').insert({'session_id':sid,'role':'user','content':body.message}).execute()
    key = provider_key("openrouter")
    provider = Provider(key, credential_check=credential_guard("openrouter", key))
    result = run_analysis(body.message, [{'role':r['role'],'content':r['content']} for r in history], scope, adapter, provider)
    scope = result['evidence']['scope']
    data_version = result['evidence']['data_version']
    saved = db.table('chat_messages').insert({'session_id':sid,'role':'assistant','content':result['answer'],
        'tool_context':{'analysis_scope':scope,'definition_version':result['definition_version'],
                        'tool_calls':result['tool_trace'],'data_version':data_version, 'telemetry':provider.telemetry}}).execute().data[0]
    pending = None
    if result['missing_requirements'] and not resumed:
        pending = db.table('advisor_pending_analysis').insert({'user_id':uid,'session_id':sid,'question':body.message,
            'month':scope['month'],'requirements':result['missing_requirements'],'data_version':data_version}).execute().data[0]
    return {'session_id':sid,'message_id':saved['id'],'answer':result['answer'],'pending':pending}


@router.get('/analysis/config')
async def config(user=Depends(get_current_user)):
    return {'enabled':settings.evidence_advisor_enabled}


@router.post('/analysis')
async def analysis(body: AnalysisRequest, user=Depends(get_current_user)):
    enabled()
    try:
        return await asyncio.to_thread(analyze,get_admin_db(),str(user.id),body)
    except (HTTPException, CredentialError): raise
    except Exception:
        logger.exception('Evidence analysis failed')
        raise HTTPException(502, 'Analysis could not be completed. No unverified answer was shown.') from None


@router.get('/sessions/{session_id}/pending-analysis')
async def pending_analysis(session_id: str, user=Depends(get_current_user)):
    enabled()
    db, uid = get_admin_db(), str(user.id)
    owned_session(db,uid,session_id)
    rows = db.table('advisor_pending_analysis').select('*').eq('user_id',uid).eq('session_id',session_id).eq('status','waiting').order('created_at',desc=True).limit(1).execute().data
    if not rows: return {'pending':None}
    pending = rows[0]
    adapter = await asyncio.to_thread(live_adapter,db,uid,pending['month'])
    return {'pending':pending | readiness(pending,adapter.context().get('availability',{}),adapter.version)}


@router.post('/pending-analysis/{pending_id}/resume')
async def resume(pending_id: str, user=Depends(get_current_user)):
    enabled()
    db, uid = get_admin_db(), str(user.id)
    rows = db.table('advisor_pending_analysis').select('*').eq('id',pending_id).eq('user_id',uid).execute().data
    if not rows: raise HTTPException(404,'Pending analysis not found')
    pending = rows[0]
    owned_session(db,uid,pending['session_id'])
    try: state = claim_state(pending['status'])
    except ValueError: raise HTTPException(409,'Analysis is running or needs recovery') from None
    if state == 'cached': return pending['result']
    adapter = await asyncio.to_thread(live_adapter,db,uid,pending['month'])
    if not readiness(pending,adapter.context().get('availability',{}),adapter.version)['ready']:
        raise HTTPException(409,'Required data is still missing or unchanged')
    claimed = db.rpc('claim_pending_analysis',{'p_id':pending_id,'p_user_id':uid}).execute().data
    if not claimed: raise HTTPException(409,'Another request already started this analysis')
    try:
        result = await asyncio.to_thread(analyze,db,uid,AnalysisRequest(message=pending['question'],session_id=pending['session_id'],month=pending['month']),adapter=adapter,resumed=True)
        db.table('advisor_pending_analysis').update({'status':'complete','result':result}).eq('id',pending_id).eq('user_id',uid).execute()
        return result
    except CredentialError:
        db.table('advisor_pending_analysis').update({'status':'failed'}).eq('id',pending_id).eq('user_id',uid).execute()
        raise
    except Exception:
        db.table('advisor_pending_analysis').update({'status':'failed'}).eq('id',pending_id).eq('user_id',uid).execute()
        logger.exception('Resumed evidence analysis failed')
        raise HTTPException(502,'Continuation failed; it will not be retried automatically.') from None
