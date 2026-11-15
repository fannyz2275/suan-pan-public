import asyncio
import pytest
from app.advisor.resilience import call_tool_with_timeout


@pytest.mark.asyncio
async def test_call_tool_with_timeout_returns_result_on_success():
    async def fake_call(name, args):
        return {"ok": True, "name": name}
    res = await call_tool_with_timeout(fake_call, "x", {"a": 1}, timeout=1.0)
    assert res == {"ok": True, "name": "x"}


@pytest.mark.asyncio
async def test_call_tool_with_timeout_returns_error_on_hang():
    async def hanging(name, args):
        await asyncio.sleep(5)
    res = await call_tool_with_timeout(hanging, "x", {}, timeout=0.05)
    assert res == {"error": "tool_timeout", "tool": "x"}


from app.advisor.resilience import stream_with_retry


@pytest.mark.asyncio
async def test_stream_with_retry_succeeds_first_try():
    calls = [0]

    async def factory():
        calls[0] += 1

        async def _g():
            yield 1
            yield 2
        return _g()
    out = []
    async for x in await stream_with_retry(factory, max_attempts=2, backoff=(0.01, 0.02)):
        out.append(x)
    assert out == [1, 2]
    assert calls[0] == 1


@pytest.mark.asyncio
async def test_stream_with_retry_retries_transient():
    from app.advisor.resilience import TransientError
    calls = [0]

    async def factory():
        calls[0] += 1
        if calls[0] < 2:
            raise TransientError("429")

        async def _g():
            yield "ok"
        return _g()
    out = [x async for x in await stream_with_retry(factory, max_attempts=3, backoff=(0.01, 0.02))]
    assert out == ["ok"]
    assert calls[0] == 2


from app.advisor.resilience import fallback_message


def test_fallback_for_max_turns():
    msg = fallback_message(full_response="", tool_turns=10, max_turns=10)
    assert "narrowing" in msg.lower()


def test_fallback_for_empty():
    msg = fallback_message(full_response="", tool_turns=0, max_turns=10)
    assert "rephrasing" in msg.lower()


def test_fallback_none_when_response_present():
    assert fallback_message(full_response="hi", tool_turns=0, max_turns=10) is None
