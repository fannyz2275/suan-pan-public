from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FindingKind = Literal["recurring", "transfer"]
DecisionValue = Literal["accept", "reject"]


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: FindingKind
    title: str
    body: str
    evidence: dict = Field(default_factory=dict)
    created_at: datetime


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: DecisionValue
