from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class AccountType(str, Enum):
    checking = "checking"
    savings = "savings"
    brokerage = "brokerage"
    retirement = "retirement"
    property = "property"
    rsu = "rsu"
    business = "business"
    debt = "debt"


class AccountCreate(BaseModel):
    name: str
    type: AccountType
    balance: float = 0.0
    nickname: Optional[str] = None
    account_number_last4: Optional[str] = Field(default=None, pattern=r"^\d{4}$")
    vested_shares: Optional[float] = None
    unvested_shares: Optional[float] = None
    grant_price: Optional[float] = None
    vesting_schedule: Optional[List[dict]] = None
    estimated_value: Optional[float] = None
    purchase_price: Optional[float] = None
    ownership_pct: Optional[float] = None
    estimated_valuation: Optional[float] = None
    liquidity_horizon_months: Optional[int] = None


class AccountOut(AccountCreate):
    id: str
    user_id: str
    source: str
    created_at: datetime
    # Server-computed display value for the account, used by the UI as the
    # "primary value" instead of the raw balance (which is misleading for
    # property / RSU / business accounts). Mirrors snapshot._notional_value.
    notional_value: Optional[float] = None
    # Balance-history trail used by the Accounts UI to warn the user when a
    # statement upload has overwritten a hand-entered number.
    balance_updated_at: Optional[datetime] = None
    previous_balance: Optional[float] = None
    previous_balance_at: Optional[datetime] = None


class GoalType(str, Enum):
    savings = "savings"
    debt_payoff = "debt_payoff"
    investment = "investment"
    life_event = "life_event"


class GoalCreate(BaseModel):
    name: str
    type: GoalType
    target_amount: float
    target_date: str
    notes: Optional[str] = None
    is_primary: bool = False


class GoalUpdate(BaseModel):
    """Partial update — every field optional. Used by PATCH /finance/goals/{id}.

    Kept separate from GoalCreate so callers can flip a single field (e.g.
    `is_primary`) without re-sending the full goal payload."""
    name: Optional[str] = None
    type: Optional[GoalType] = None
    target_amount: Optional[float] = None
    target_date: Optional[str] = None
    notes: Optional[str] = None
    is_primary: Optional[bool] = None


class GoalOut(GoalCreate):
    id: str
    user_id: str
    current_progress: float
    feasibility_score: Optional[float]
    status: str
    created_at: datetime


class TransactionOut(BaseModel):
    id: str
    user_id: str
    account_id: Optional[str] = None
    date: str
    description: str
    amount: float
    category: Optional[str] = None
    source: str
    created_at: datetime
    transfer_group_id: Optional[str] = None
    transfer_status: Optional[str] = None
