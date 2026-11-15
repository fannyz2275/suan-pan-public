"""Retry-free OpenRouter calls for the live evidence-first pipeline."""
import json
import time
import httpx
from app.provider_credentials.crypto import CredentialError

MODELS = {'planner':'google/gemini-2.5-flash', 'writer':'deepseek/deepseek-v3.2'}


class Provider:
    def __init__(self, api_key, *, client=None, credential_check=None):
        if not api_key:
            raise ValueError('OPENROUTER_API_KEY is required')
        self._key = api_key
        self._credential_check = credential_check
        self.client = client
        self.telemetry = []

    def complete(self, role, messages, *, max_tokens, response_format=None):
        if self._credential_check: self._credential_check()
        try:
            return self._complete(role, messages, max_tokens=max_tokens, response_format=response_format)
        except Exception:
            raise CredentialError('OpenRouter request failed. Check your key, model access, and quota in Settings.') from None

    def _complete(self, role, messages, *, max_tokens, response_format=None):
        if role not in MODELS:
            raise ValueError('Unknown provider role')
        body = {'model':MODELS[role], 'messages':messages, 'max_tokens':max_tokens,
                'response_format':response_format or {'type':'json_object'},
                'provider':{'allow_fallbacks':False, 'require_parameters':True},
                'reasoning':{'enabled':False} if role == 'writer' else {'effort':'low'}}
        started = time.monotonic()
        with httpx.Client(transport=httpx.HTTPTransport(retries=0), trust_env=False) as default_client:
            response = (self.client or default_client).post('https://openrouter.ai/api/v1/chat/completions',
                json=body, headers={'Authorization':'Bearer ' + self._key}, timeout=120)
        response.raise_for_status()
        payload = response.json()
        self.telemetry.append({'role':role, 'model':payload.get('model'), 'usage':payload.get('usage'),
                               'latency_seconds':time.monotonic() - started})
        if payload.get('model') != MODELS[role]:
            raise ValueError('Unexpected provider model')
        return json.loads(payload['choices'][0]['message']['content'])
