from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tool: Literal['summary', 'contributors', 'investments', 'transfers', 'wealth']
    group: Literal['category', 'merchant', 'income_source', 'refund_source'] = 'category'
    measure: Literal['current', 'change', 'absolute_change'] = 'current'
    limit: int = Field(default=3, ge=1, le=10)


class EvidencePlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    month: str | None = Field(default=None, pattern=r'^\d{4}-\d{2}$')
    task: Literal['general', 'income_summary', 'income_change', 'wealth_change'] = 'general'
    requests: list[ToolRequest] = Field(default_factory=list, max_length=6)
    requirements: list[Literal['aligned_wealth', 'period_security_returns', 'complete_cost_basis', 'peer_benchmark', 'verified_refund_data']] = Field(default_factory=list, max_length=5)


class NarrativeBlock(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str | None = Field(default=None, max_length=1800)
    ranking: str | None = None


class Narrative(BaseModel):
    model_config = ConfigDict(extra='forbid')
    blocks: list[NarrativeBlock] = Field(min_length=1, max_length=8)
