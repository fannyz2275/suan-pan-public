"""Unit tests for app.notes.importance — score_importance + _parse."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.notes.importance import _parse, score_importance
from app.notes.schema import DEFAULT_IMPORTANCE, NoteKind


def test_parse_pure_integer():
    assert _parse("7") == 7


def test_parse_with_whitespace():
    assert _parse("  3  ") == 3


def test_parse_with_lead_in_text():
    # "Importance: 8" — first run of digits is what we want.
    assert _parse("Importance: 8") == 8


def test_parse_with_markdown_decoration():
    assert _parse("**6**") == 6


def test_parse_out_of_range_falls_back():
    assert _parse("47") == DEFAULT_IMPORTANCE
    assert _parse("0") == DEFAULT_IMPORTANCE


def test_parse_no_digits_falls_back():
    assert _parse("not sure") == DEFAULT_IMPORTANCE


def test_parse_none_or_empty_falls_back():
    assert _parse(None) == DEFAULT_IMPORTANCE
    assert _parse("") == DEFAULT_IMPORTANCE


@pytest.mark.asyncio
async def test_score_importance_with_none_gemini_returns_default():
    out = await score_importance(None, "won't tap 401k", NoteKind.PREFERENCE)
    assert out == DEFAULT_IMPORTANCE


@pytest.mark.asyncio
async def test_score_importance_with_blank_content_returns_default():
    # If content is empty, we don't even bother calling Gemini.
    fake = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
        generate_content=AsyncMock()
    )))
    out = await score_importance(fake, "   ", NoteKind.FACT)
    assert out == DEFAULT_IMPORTANCE
    fake.aio.models.generate_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_score_importance_parses_gemini_response():
    fake = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
        generate_content=AsyncMock(return_value=SimpleNamespace(text="9"))
    )))
    out = await score_importance(fake, "user is the sole earner with 3 dependents", NoteKind.FACT)
    assert out == 9


@pytest.mark.asyncio
async def test_score_importance_handles_gemini_exception():
    async def raises(*args, **kwargs):
        raise RuntimeError("gemini down")
    fake = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
        generate_content=raises
    )))
    out = await score_importance(fake, "anything", NoteKind.PREFERENCE)
    assert out == DEFAULT_IMPORTANCE
