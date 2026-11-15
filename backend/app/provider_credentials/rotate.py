"""Operator-only re-encryption: python -m app.provider_credentials.rotate."""
from uuid import uuid4
from app.config import settings
from app.db import get_admin_db
from .crypto import keyring, seal, unseal
from .store import TABLE


def rotate(db):
    keyring()
    changed=0
    offset=0
    while True:
        rows=db.table(TABLE).select('*').order('user_id').order('provider').range(offset,offset+499).execute().data or []
        for r in rows:
            if r['encryption_key_version']==settings.provider_keys_active_version: continue
            secret=unseal(r['user_id'],r['provider'],r['ciphertext'],r['encryption_key_version'])
            ciphertext,version=seal(r['user_id'],r['provider'],secret)
            updated=db.table(TABLE).update({'ciphertext':ciphertext,'encryption_key_version':version,'revision':str(uuid4())}).eq(
                'user_id',r['user_id']).eq('provider',r['provider']).eq('revision',r['revision']).execute().data
            changed+=len(updated or [])
        if len(rows)<500: return changed
        offset+=500

if __name__=='__main__':
    try: print(f'Re-encrypted {rotate(get_admin_db())} credentials. Keep old encryption keys until all rows are verified.')
    except Exception: raise SystemExit('Rotation failed. Retain old encryption keys and check configuration/storage; no secrets printed.') from None
