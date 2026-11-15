"""Authenticated encryption; never expose provider credentials in exceptions."""
import json
from cryptography.fernet import Fernet
from app.config import settings

PROVIDERS = ('gemini', 'openrouter')

class CredentialError(Exception):
    def __init__(self, message='AI provider unavailable. Open Settings → AI providers.', status=503):
        super().__init__(message)
        self.status = status


def keyring():
    try:
        keys = json.loads(settings.provider_keys_encryption_keys)
        if not isinstance(keys, dict) or not keys or settings.provider_keys_active_version not in keys:
            raise ValueError()
        return {version: Fernet(value.encode()) for version, value in keys.items()}
    except Exception:
        raise CredentialError('AI key storage is not configured. Ask the operator to configure encryption.') from None


def seal(uid, provider, secret):
    version = settings.provider_keys_active_version
    payload = json.dumps({'v':1,'user_id':str(uid),'provider':provider,'key':secret}).encode()
    return keyring()[version].encrypt(payload).decode(), version


def unseal(uid, provider, ciphertext, version):
    keys = keyring()
    try:
        payload = json.loads(keys[version].decrypt(ciphertext.encode()))
        if (payload['v'],payload['user_id'],payload['provider']) != (1,str(uid),provider):
            raise ValueError()
        return payload['key']
    except Exception:
        raise CredentialError('Saved AI key could not be decrypted. Contact the operator or replace it in Settings.') from None
