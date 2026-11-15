import pytest
from tests.integration.mock_gemini import MockGeminiClient, ChunkText, ChunkToolCall

@pytest.mark.asyncio
async def test_mock_replays_scripted_sequence():
    client = MockGeminiClient()
    client.enqueue([ChunkText("Hello "), ChunkText("world")])
    stream = await client.aio.models.generate_content_stream(model="x", contents=[], config=None)
    chunks = [c async for c in stream]
    assert [c.text for c in chunks] == ["Hello ", "world"]

@pytest.mark.asyncio
async def test_mock_replays_tool_call_then_text():
    client = MockGeminiClient()
    client.enqueue([ChunkToolCall("get_transactions", {"date_from": "2025-12-01", "date_to": "2025-12-31"})])
    client.enqueue([ChunkText("Here are your transactions.")])
    # Round 1
    round1 = [c async for c in await client.aio.models.generate_content_stream(model="x", contents=[], config=None)]
    assert round1[0].function_calls[0].name == "get_transactions"
    # Round 2
    round2 = [c async for c in await client.aio.models.generate_content_stream(model="x", contents=[], config=None)]
    assert round2[0].text == "Here are your transactions."
