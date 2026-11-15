"""Local synthetic provider-key harness. Never deploy. No external provider calls."""
import json
from types import SimpleNamespace
from cryptography.fernet import Fernet
from fastapi import Header
from tests.forecast_test_server import app
from tests.forecast_fixture import UID
from tests.test_provider_credentials import DB
from app.config import settings
from app.provider_credentials import router as keys

settings.provider_keys_encryption_keys=json.dumps({'test':Fernet.generate_key().decode()})
settings.provider_keys_active_version='test'
TEST_KEYRING=settings.provider_keys_encryption_keys
storage=DB()
app.include_router(keys.router)
app.dependency_overrides[keys.database]=lambda: storage
async def user(x_test_user: str = Header(default=UID)):
    return SimpleNamespace(id=x_test_user)
app.dependency_overrides[keys.get_current_user]=user
async def probe(provider,secret): return not secret.endswith('invalid')
keys.probe=probe

@app.post('/reset-keys')
def reset_keys(disabled: bool=False):
    storage.rows.clear()
    settings.provider_keys_encryption_keys='' if disabled else TEST_KEYRING
    return {'ok':True}

@app.get('/key-storage-audit')
def audit():
    return {'rows':len(storage.rows),'encrypted':all(r['ciphertext'].startswith('gAAAA') for r in storage.rows)}
