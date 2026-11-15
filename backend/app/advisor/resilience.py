import asyncio
import logging

logger = logging.getLogger(__name__)


async def call_tool_with_timeout(call_fn, name: str, args: dict, *, timeout: float = 30.0) -> dict:
    """Invoke an async tool-call function with a timeout. Returns a result dict.

    On TimeoutError, returns {"error": "tool_timeout", "tool": name} — shaped so the
    advisor can narrate the failure the same way it handles real tool errors.
    """
    try:
        return await asyncio.wait_for(call_fn(name, args), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Tool call %s timed out after %ss", name, timeout)
        return {"error": "tool_timeout", "tool": name}


class TransientError(Exception):
    """Raised by callers to signal a retryable Gemini failure (429/503/transient)."""


async def stream_with_retry(factory, *, max_attempts: int = 3, backoff: tuple[float, ...] = (1.0, 3.0)):
    """Call factory() to obtain an async iterable; retry on TransientError.

    factory: zero-arg async callable returning an async iterable.
    Returns the async iterable from the successful call.
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await factory()
        except TransientError as e:
            last_exc = e
            if attempt + 1 >= max_attempts:
                break
            delay = backoff[min(attempt, len(backoff) - 1)]
            logger.warning(
                "Retrying Gemini stream (attempt %d/%d): %s",
                attempt + 1,
                max_attempts,
                e,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


def classify_gemini_error(exc: BaseException) -> bool:
    """Return True if the error is transient (worth retrying)."""
    from app.provider_credentials.crypto import CredentialError
    if isinstance(exc, CredentialError):
        return bool(getattr(exc, "retryable", False))
    msg = str(exc).lower()
    if "429" in msg or "resource exhausted" in msg or ("rate" in msg and "limit" in msg):
        return True
    if "503" in msg or "unavailable" in msg:
        return True
    return False


def fallback_message(
    *,
    full_response: str,
    tool_turns: int,
    max_turns: int,
    session_message_count: int = 0,
    last_user_message_len: int = 0,
) -> str | None:
    if full_response.strip():
        return None
    if tool_turns >= max_turns:
        logger.warning(
            "fallback_message fired: max_turns reached",
            extra={
                "cause": "max_tool_turns",
                "tool_turns": tool_turns,
                "max_turns": max_turns,
                "session_message_count": session_message_count,
                "last_user_message_len": last_user_message_len,
            },
        )
        return (
            "I used several tool calls but couldn't form a clear answer. "
            "Try narrowing your question — for example, a specific date range or category."
        )
    logger.warning(
        "fallback_message fired: empty stream output",
        extra={
            "cause": "empty_stream",
            "tool_turns": tool_turns,
            "session_message_count": session_message_count,
            "last_user_message_len": last_user_message_len,
        },
    )
    return "I didn't generate a response. Please try rephrasing your question."
