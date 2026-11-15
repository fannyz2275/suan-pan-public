"""Adapt OpenRouter streaming to the advisor's existing guarded tool loop."""
import json
from types import SimpleNamespace

import httpx
from google.genai import types

from app.provider_credentials.crypto import CredentialError
from app.provider_credentials.scope import credential_guard, gemini_client, provider_key, safe_error


def chat_client():
    try:
        key = provider_key('openrouter')
    except CredentialError as exc:
        if exc.status != 409:
            raise
        return gemini_client()
    return OpenRouterChat(key, credential_guard('openrouter', key))


def json_schema(value):
    if isinstance(value, list):
        return [json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {key: (item.lower() if key == 'type' and isinstance(item, str) else json_schema(item))
            for key, item in value.items() if key != 'propertyOrdering'}


def messages_for(contents, system):
    messages = [{'role': 'system', 'content': system}] if system else []
    pending = []
    for content in contents:
        text = ''.join(part.text or '' for part in content.parts or [])
        calls = []
        for part in content.parts or []:
            if part.function_call:
                fc = part.function_call
                call_id = fc.id or f'call_{len(messages)}_{len(calls)}'
                calls.append({'id': call_id, 'type': 'function', 'function': {
                    'name': fc.name, 'arguments': json.dumps(fc.args or {})}})
                pending.append((fc.name, call_id))
            if part.function_response:
                response = part.function_response
                index = next(i for i, (name, _) in enumerate(pending) if name == response.name)
                _, call_id = pending.pop(index)
                messages.append({'role': 'tool', 'tool_call_id': call_id,
                                 'content': json.dumps(response.model_dump(mode='json')['response'])})
        if text or calls:
            message = {'role': 'assistant' if content.role == 'model' else 'user', 'content': text or None}
            if calls:
                message['tool_calls'] = calls
            messages.append(message)
    return messages


class OpenRouterChat:
    def __init__(self, key, check, *, transport=None):
        self._key, self._check, self._transport = key, check, transport
        self.aio = self.models = self

    async def generate_content_stream(self, *, contents, config, model):
        self._check()
        body = {'model': 'google/gemini-2.5-flash', 'stream': True,
                'messages': messages_for(contents, config.system_instruction),
                'max_tokens': config.max_output_tokens or 4096}
        declarations = []
        for tool in config.tools or []:
            for function in tool.function_declarations or []:
                schema = function.parameters_json_schema
                if schema is None and function.parameters:
                    schema = function.parameters.model_dump(exclude_none=True, by_alias=True)
                declarations.append({'type': 'function', 'function': {
                    'name': function.name, 'description': function.description or '',
                    'parameters': json_schema(schema or {'type': 'object', 'properties': {}})}})
        if declarations:
            body['tools'] = declarations

        async def stream():
            calls = {}
            try:
                async with httpx.AsyncClient(timeout=120, trust_env=False, transport=self._transport) as client:
                    async with client.stream('POST', 'https://openrouter.ai/api/v1/chat/completions',
                                             headers={'Authorization': 'Bearer ' + self._key}, json=body) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.startswith('data:'):
                                continue
                            data = line[5:].strip()
                            if data == '[DONE]':
                                break
                            event = json.loads(data)
                            if event.get('error'):
                                raise CredentialError('OpenRouter request failed. Check your saved key, model access, and quota in Settings.')
                            for choice in event.get('choices', []):
                                if choice.get('finish_reason') == 'error':
                                    raise CredentialError('OpenRouter could not finish this response. Please retry.')
                                delta = choice.get('delta', {})
                                if delta.get('content'):
                                    yield SimpleNamespace(text=delta['content'], function_calls=[])
                                for call in delta.get('tool_calls', []):
                                    entry = calls.setdefault(call['index'], {'id': '', 'name': '', 'arguments': ''})
                                    entry['id'] += call.get('id', '')
                                    for key in ('name', 'arguments'):
                                        entry[key] += call.get('function', {}).get(key, '')
                if calls:
                    functions = [types.FunctionCall(id=c['id'], name=c['name'], args=json.loads(c['arguments'] or '{}'))
                                 for _, c in sorted(calls.items())]
                    yield SimpleNamespace(text=None, function_calls=functions)
            except CredentialError:
                raise
            except Exception as exc:
                # Never propagate HTTP request headers or upstream response bodies.
                if isinstance(exc, httpx.HTTPStatusError):
                    safe = safe_error(SimpleNamespace(status_code=exc.response.status_code))
                else:
                    safe = safe_error(exc)
                raise safe from None
        source = stream()
        # Surface pre-output HTTP errors to the existing retry controller.
        try:
            first = await anext(source)
        except StopAsyncIteration:
            first = None

        async def opened_stream():
            try:
                if first is not None:
                    yield first
                async for chunk in source:
                    yield chunk
            finally:
                await source.aclose()
        return opened_stream()
