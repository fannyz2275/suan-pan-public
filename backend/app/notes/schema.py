"""Pydantic types for user_notes rows."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class NoteKind(str, Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    EXAMPLE = "example"


class NoteSource(str, Enum):
    CHAT_EXTRACTION = "chat_extraction"
    MESSAGE_FEEDBACK = "message_feedback"
    ENTITY_EDIT = "entity_edit"
    COMPACTION_MERGE = "compaction_merge"


DEFAULT_IMPORTANCE = 5  # median; used when Gemini scoring is unavailable.


class Note(BaseModel):
    id: UUID
    user_id: UUID
    kind: NoteKind
    content: str
    tags: list[str] = Field(default_factory=list)
    entity_refs: dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[list[float]] = None
    source: NoteSource
    provenance: dict[str, Any] = Field(default_factory=dict)
    strength: int = Field(default=1, ge=1)
    importance: int = Field(default=DEFAULT_IMPORTANCE, ge=1, le=10)
    last_accessed_at: Optional[datetime] = None
    supersedes: list[UUID] = Field(default_factory=list)
    superseded_by: Optional[UUID] = None
    expires_at: Optional[datetime] = None
    created_at: datetime


class NewNote(BaseModel):
    """Insert-shape for store.insert_note. id/created_at come from the DB."""
    user_id: UUID
    kind: NoteKind
    content: str
    tags: list[str] = Field(default_factory=list)
    entity_refs: dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[list[float]] = None
    source: NoteSource
    provenance: dict[str, Any] = Field(default_factory=dict)
    strength: int = Field(default=1, ge=1)
    # importance left optional so callers that don't have a Gemini handle
    # (entity-edit hot path, tests) can omit it; insert_note defaults to 5
    # and the offline backfill job re-scores later.
    importance: Optional[int] = Field(default=None, ge=1, le=10)
    expires_at: Optional[datetime] = None


@dataclass
class ScoredNote:
    """A retrieved note paired with its raw + final scores. The breakdown is
    surfaced so callers (eval harness, debug endpoint) can audit ranking
    decisions without re-running the pipeline."""
    note: Note
    raw_relevancy: float
    raw_recency: float
    raw_importance: float
    score: float
