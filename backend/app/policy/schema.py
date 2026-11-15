"""Pydantic types for user_engine_overrides rows + domain enum.

Keep these aligned with the SQL CHECK constraint on `domain` and the
domain-specific `value` JSONB shapes documented per-domain in the
implementation modules (see app/policy/categorize.py for the first one).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class Domain(str, Enum):
    CATEGORIZE = "categorize"
    TRANSFERS = "transfers"
    RECURRING = "recurring"
    FEASIBILITY = "feasibility"
    BASELINE = "baseline"


class Override(BaseModel):
    id: UUID
    user_id: UUID
    domain: Domain
    key: str
    value: dict[str, Any] = Field(default_factory=dict)
    source_note_id: Optional[UUID] = None
    strength: int = Field(default=1, ge=1)
    created_at: datetime
    last_reinforced_at: datetime
    retired_at: Optional[datetime] = None
