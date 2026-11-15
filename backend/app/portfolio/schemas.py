from datetime import date, datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class HoldingIn(BaseModel):
    ticker: str
    quantity: float
    price: float
    cost_basis: Optional[float] = None


class HoldingOut(BaseModel):
    ticker: str
    name: Optional[str] = None
    quantity: float
    price: float
    market_value: float
    percent: float
    cost_basis: Optional[float] = None
    unrealized_gain: Optional[float] = None


class ManualSnapshotIn(BaseModel):
    account_id: UUID
    snapshot_date: date
    cash_value: float = 0
    holdings: List[HoldingIn] = Field(default_factory=list)


class SnapshotOut(BaseModel):
    id: UUID
    account_id: UUID
    snapshot_date: date
    source: Literal["plaid", "statement_import", "manual"]
    total_value: float
    cash_value: float
    holdings: List[HoldingOut]
    created_at: datetime


class TimeSeriesPoint(BaseModel):
    date: date
    total_value: float


class PortfolioValueOut(BaseModel):
    total_value: float
    as_of: Optional[date] = None
    account_count: int = 0


class LookThroughHolding(BaseModel):
    ticker: str
    name: Optional[str] = None
    sector: Optional[str] = None
    country: Optional[str] = None
    market_value: float
    percent: float
    via: List[str] = Field(default_factory=list)


class ExposureSlice(BaseModel):
    label: str
    market_value: float
    percent: float


class PortfolioSummary(BaseModel):
    total_value: float
    period_change: float
    period_change_pct: float
    top_holdings: List[HoldingOut]
    as_of: date


class StatementHolding(BaseModel):
    ticker: str
    name: Optional[str] = None
    quantity: float
    price: float
    market_value: float
    cost_basis: Optional[float] = None


class StatementInvestmentTxn(BaseModel):
    date: date
    type: Literal[
        "buy", "sell", "dividend", "interest", "fee",
        "transfer_in", "transfer_out", "split", "reinvest",
    ]
    ticker: Optional[str] = None
    quantity: Optional[float] = None
    price: Optional[float] = None
    amount: float


class StatementPreview(BaseModel):
    statement_date: date
    cash_value: float = 0
    holdings: List[StatementHolding] = Field(default_factory=list)
    investment_transactions: List[StatementInvestmentTxn] = Field(default_factory=list)
    account_hint: Optional[str] = None  # account name / number last4 if visible
    total_value_reported: Optional[float] = None  # value the statement explicitly shows; used for tie-out vs. cash + Σ(qty × price)


class StatementImportConfirm(BaseModel):
    account_id: UUID
    statement_date: date
    cash_value: float = 0
    holdings: List[StatementHolding] = Field(default_factory=list)
    investment_transactions: List[StatementInvestmentTxn] = Field(default_factory=list)


class MacroContext(BaseModel):
    """Macro snapshot for the attribution window (FRED + SPY)."""
    ten_year_yield_change_bps: Optional[float] = None
    cpi_yoy_at_end: Optional[float] = None
    spy_period_return_pct: Optional[float] = None


class AttributionResult(BaseModel):
    from_date: date
    to_date: date
    start_value: float
    end_value: float
    contributions: float
    withdrawals: float
    dividends: float
    trades: float
    trades_has_basis: bool
    market: float
    unattributed: float
    macro_context: Optional[MacroContext] = None


class MacroOverlayPoint(BaseModel):
    date: date
    ten_year_yield: Optional[float] = None  # percent, e.g. 4.20
    cpi_yoy: Optional[float] = None         # percent, e.g. 3.10
    spy_close: Optional[float] = None       # raw $; UI normalizes to indexed


class TimeSeriesResponse(BaseModel):
    series: List[TimeSeriesPoint]
    overlays: List[MacroOverlayPoint] = Field(default_factory=list)
    unpriced_tickers: List[str] = Field(default_factory=list)
    snapshot_dates: List[date] = Field(default_factory=list)
