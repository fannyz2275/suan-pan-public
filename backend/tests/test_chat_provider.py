import json
from unittest.mock import Mock
import httpx
import pytest
from google.genai import types


def test_openrouter_selected_without_gemini(monkeypatch):
    from app.advisor import chat_provider as p
    monkeypatch.setattr(p, 'provider_key', lambda provider: 'synthetic-openrouter')
    gemini = Mock(side_effect=AssertionError('Gemini must not be initialized'))
    monkeypatch.setattr(p, 'gemini_client', gemini)
    assert isinstance(p.chat_client(), p.OpenRouterChat)
    gemini.assert_not_called()


def test_missing_openrouter_uses_gemini_but_storage_errors_do_not(monkeypatch):
    from app.advisor import chat_provider as p
    from app.provider_credentials.crypto import CredentialError
    def missing(_): raise CredentialError('missing',409)
    monkeypatch.setattr(p, 'provider_key', missing)
    monkeypatch.setattr(p, 'gemini_client', lambda: 'gemini-client')
    assert p.chat_client() == 'gemini-client'
    def broken(_): raise CredentialError('storage unavailable',503)
    monkeypatch.setattr(p, 'provider_key', broken)
    with pytest.raises(CredentialError): p.chat_client()


@pytest.mark.asyncio
async def test_stream_and_parallel_tool_results_roundtrip():
    from app.advisor.chat_provider import OpenRouterChat
    requests=[]
    def respond(request):
        body=json.loads(request.content); requests.append(body)
        delta={'tool_calls':[{'index':0,'id':'a','function':{'name':'snapshot','arguments':'{}'}},
                             {'index':1,'id':'b','function':{'name':'snapshot','arguments':'{}'}}]} if len(requests)==1 else {'content':'Your answer'}
        return httpx.Response(200,text='data: '+json.dumps({'choices':[{'delta':delta}]})+'\n\ndata: [DONE]\n\n')
    checks=Mock()
    p=OpenRouterChat('synthetic',checks,transport=httpx.MockTransport(respond))
    config=types.GenerateContentConfig(system_instruction='Use facts',tools=[types.Tool(function_declarations=[types.FunctionDeclaration(name='snapshot',parameters=types.Schema(type='OBJECT',properties={'month':types.Schema(type='STRING')}))])])
    contents=[types.Content(role='user',parts=[types.Part(text='recurring transfers?')])]
    stream=await p.generate_content_stream(contents=contents,config=config,model='unused')
    chunks=[c async for c in stream]
    calls=chunks[0].function_calls
    assert [c.id for c in calls]==['a','b']
    contents.extend([types.Content(role='model',parts=[types.Part(function_call=c) for c in calls]),types.Content(role='user',parts=[types.Part.from_function_response(name='snapshot',response={'n':n}) for n in [1,2]])])
    stream=await p.generate_content_stream(contents=contents,config=config,model='unused')
    assert [c.text async for c in stream]==['Your answer']
    assert [m['tool_call_id'] for m in requests[1]['messages'] if m['role']=='tool']==['a','b']
    assert requests[0]['tools'][0]['function']['parameters']['type']=='object'
    assert checks.call_count==2


@pytest.mark.asyncio
async def test_provider_failure_does_not_expose_key():
    from app.advisor.chat_provider import OpenRouterChat
    from app.provider_credentials.crypto import CredentialError
    p=OpenRouterChat('secret',lambda:None,transport=httpx.MockTransport(lambda _:httpx.Response(403,text='secret')))
    with pytest.raises(CredentialError) as exc:
        await p.generate_content_stream(contents=[],config=types.GenerateContentConfig(),model='unused')
    assert 'secret' not in str(exc.value)


@pytest.mark.asyncio
async def test_fragmented_tool_arguments_and_changed_key():
    from app.advisor.chat_provider import OpenRouterChat
    from app.provider_credentials.crypto import CredentialError
    events=[{'tool_calls':[{'index':0,'id':'call1','function':{'name':'lookup','arguments':'{"month":'}}]},
            {'tool_calls':[{'index':0,'function':{'arguments':'"2026-09"}'}}]}]
    def respond(_):
        return httpx.Response(200,text=''.join('data: '+json.dumps({'choices':[{'delta':delta}]})+'\n\n' for delta in events)+'data: [DONE]\n\n')
    check=Mock()
    p=OpenRouterChat('synthetic',check,transport=httpx.MockTransport(respond))
    stream=await p.generate_content_stream(contents=[],config=types.GenerateContentConfig(),model='unused')
    chunks=[chunk async for chunk in stream]
    assert chunks[0].function_calls[0].args=={'month':'2026-09'}
    check.side_effect=CredentialError('Key changed')
    with pytest.raises(CredentialError,match='Key changed'):
        await p.generate_content_stream(contents=[],config=types.GenerateContentConfig(),model='unused')


@pytest.mark.asyncio
async def test_real_mcp_text_content_is_sent_as_json_to_openrouter():
    from mcp.types import CallToolResult, TextContent
    from app.advisor.chat_provider import OpenRouterChat
    result=CallToolResult(content=[TextContent(type='text',text='{"recurring_transfers":[],"coverage":"unverified"}')])
    response=types.FunctionResponse.from_mcp_response(name='recurring_transfers',response=result)
    contents=[
        types.Content(role='model',parts=[types.Part(function_call=types.FunctionCall(id='transfer-1',name='recurring_transfers',args={}))]),
        types.Content(role='user',parts=[types.Part(function_response=response)]),
    ]
    bodies=[]
    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200,text='data: {"choices":[{"delta":{"content":"Coverage is unverified."}}]}\n\ndata: [DONE]\n\n')
    client=OpenRouterChat('synthetic',lambda:None,transport=httpx.MockTransport(respond))
    stream=await client.generate_content_stream(contents=contents,config=types.GenerateContentConfig(),model='unused')
    assert [chunk.text async for chunk in stream]==['Coverage is unverified.']
    tool_message=bodies[0]['messages'][1]
    assert tool_message['tool_call_id']=='transfer-1'
    payload=json.loads(tool_message['content'])
    assert payload['result'][0]['text']==result.content[0].text
