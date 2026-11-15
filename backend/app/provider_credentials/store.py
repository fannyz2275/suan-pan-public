"""Service-role storage, always scoped to authenticated user and provider."""
from datetime import datetime, timezone
from uuid import uuid4
from .crypto import CredentialError, seal, unseal

TABLE = 'user_provider_credentials'
METADATA = 'provider,last_four,created_at,updated_at,validation_status,validated_at,revision'

def now(): return datetime.now(timezone.utc).isoformat()

def query(db, uid, provider):
    return db.table(TABLE).select('*').eq('user_id',str(uid)).eq('provider',provider)

def row(db, uid, provider):
    try:
        rows = query(db,uid,provider).execute().data or []
    except Exception:
        raise CredentialError('AI key storage unavailable. Ask the operator to apply the provider-keys migration.') from None
    if not rows:
        raise CredentialError(f'Add a {provider} API key in Settings → AI providers.', 409)
    return rows[0]

def get_key(db, uid, provider):
    r = row(db,uid,provider)
    return unseal(uid,provider,r['ciphertext'],r['encryption_key_version'])

def save_key(db, uid, provider, secret):
    ciphertext, version = seal(uid,provider,secret)
    stamp=now()
    try:
        db.table(TABLE).upsert({'user_id':str(uid),'provider':provider,'ciphertext':ciphertext,
            'encryption_key_version':version,'last_four':secret[-4:],'updated_at':stamp,
            'revision':str(uuid4()),'validation_status':'untested','validated_at':None},
            on_conflict='user_id,provider').execute()
    except Exception:
        raise CredentialError('AI key could not be saved. Check storage configuration.') from None

def delete_key(db, uid, provider):
    try: db.table(TABLE).delete().eq('user_id',str(uid)).eq('provider',provider).execute()
    except Exception: raise CredentialError('AI key could not be removed. Try again.') from None

def metadata(db, uid):
    try:
        rows=db.table(TABLE).select(METADATA).eq('user_id',str(uid)).execute().data or []
        return [{k:r.get(k) for k in METADATA.split(',')} for r in rows]
    except Exception:
        raise CredentialError('AI key storage unavailable. Ask the operator to apply the provider-keys migration.') from None

def record_validation(db, uid, provider, revision, valid):
    try:
        db.table(TABLE).update({'validation_status':'valid' if valid else 'failed','validated_at':now()}).eq(
            'user_id',str(uid)).eq('provider',provider).eq('revision',revision).execute()
    except Exception: raise CredentialError('Could not save validation status. Try again.') from None
