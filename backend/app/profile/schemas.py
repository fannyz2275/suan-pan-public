from typing import Literal

from pydantic import BaseModel, Field

# Legacy enum kept for the dual-write window. New code should set
# risk_tolerance_v2 (1-5 scalar). The old enum will be dropped in a
# follow-up migration once the v2 col is the read source everywhere.
RiskTolerance = Literal["conservative", "moderate", "aggressive"]
TimeHorizon = Literal["short", "medium", "long", "unknown"]
EmploymentStatus = Literal[
    "employed", "self_employed", "unemployed", "retired", "unknown"
]


class ProfileUpdate(BaseModel):
    age: int | None = Field(None, ge=0, le=120)
    dependents: int | None = Field(None, ge=0)
    use_category_baselines: bool | None = None

    # Legacy enums — accepted for back-compat until the v2 cols are the
    # only read source. New writes should target the v2 fields.
    risk_tolerance: RiskTolerance | None = None
    time_horizon: TimeHorizon | None = None

    # T1 identity scalars (1-5). Anchor sentences live in profile/scales.py.
    risk_tolerance_v2: int | None = Field(None, ge=1, le=5)
    time_horizon_v2: int | None = Field(None, ge=1, le=5)

    # Other typed identity columns added in 2026-05-02-memory-restructure-pr1.
    employment_status: EmploymentStatus | None = None
    region: str | None = Field(None, max_length=120)
