from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Frequency(str, Enum):
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    SEMI_MONTHLY = "semi_monthly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"


class Direction(str, Enum):
    INCOME = "income"
    EXPENSE = "expense"


class Status(str, Enum):
    PROPOSED = "proposed"
    PENDING_REVIEW = "pending_review"
    AUTO_APPLIED = "auto_applied"
    USER_CONFIRMED = "user_confirmed"
    USER_REJECTED = "user_rejected"


class Source(str, Enum):
    HEURISTIC = "heuristic"
    LLM = "llm"
    USER_CREATED = "user_created"


class RecurringRule(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: Optional[UUID] = None
    user_id: UUID
    keyword: str
    normalized_key_pattern: str
    amount_min: float
    amount_max: float
    amount_median: float
    frequency: Frequency
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    status: Status
    source: Source
    last_seen_date: Optional[date] = None
    next_expected_date: Optional[date] = None
    occurrences_observed: int = 0
    sample_transaction_ids: List[UUID] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _check_amount_bounds(self) -> "RecurringRule":
        if self.amount_min > self.amount_max:
            raise ValueError("amount_min must be <= amount_max")
        if not (self.amount_min <= self.amount_median <= self.amount_max):
            raise ValueError("amount_median must lie within [amount_min, amount_max]")
        return self
