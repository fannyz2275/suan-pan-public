from unittest.mock import AsyncMock, MagicMock

import pytest

from app.notes.embed import embed_text


@pytest.mark.asyncio
async def test_embed_text_returns_vector_from_gemini():
    fake_response = MagicMock()
    fake_response.embeddings = [MagicMock(values=[0.1] * 768)]
    fake_client = MagicMock()
    fake_client.aio.models.embed_content = AsyncMock(return_value=fake_response)

    vec = await embed_text(fake_client, "won't tap 401k early")

    assert vec is not None
    assert len(vec) == 768
    assert vec[0] == 0.1
    fake_client.aio.models.embed_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_embed_text_returns_none_on_failure():
    fake_client = MagicMock()
    fake_client.aio.models.embed_content = AsyncMock(side_effect=RuntimeError("boom"))

    vec = await embed_text(fake_client, "anything")

    assert vec is None
