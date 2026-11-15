"""Gemini text-embedding-004 wrapper. Returns None on failure (callers tolerate)."""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-004"
EMBEDDING_DIM = 768


async def embed_text(gemini, text: str) -> Optional[list[float]]:
    """Embed `text` via Gemini. Returns the 768-dim vector, or None on any failure.

    Embedding is best-effort: a None return must be tolerated by callers,
    and the row is stored with embedding=NULL — a later reconciliation job
    can backfill.
    """
    try:
        resp = await gemini.aio.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
        )
        emb = resp.embeddings[0]
        values = list(getattr(emb, "values", emb))
        if len(values) != EMBEDDING_DIM:
            logger.warning("embed_text: unexpected dim %d", len(values))
            return None
        return values
    except Exception:
        logger.exception("embed_text failed")
        return None
