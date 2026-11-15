"""Test the PORTFOLIO block in build_live_state_block."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.advisor.context import build_live_state_block


def _basic_snapshot():
    return {
        "net_worth": 100_000, "liquid_assets": 20_000,
        "investment_assets": 80_000, "non_current_assets": 0,
    }


def test_portfolio_block_omitted_when_no_investment_accounts():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = []

    out = build_live_state_block(
        db=db, user_id="user-1",
        snapshot=_basic_snapshot(), goals=[],
        now=datetime(2026, 5, 7, tzinfo=timezone.utc),
    )
    assert "PORTFOLIO" not in out


def test_portfolio_block_present_with_holdings():
    db = MagicMock()
    snap = {
        "id": "snap-x", "account_id": "acc-1",
        "snapshot_date": "2026-05-01", "source": "manual",
        "total_value": 10_000, "cash_value": 0,
        "created_at": "2026-05-01T00:00:00Z",
    }

    def table(name):
        t = MagicMock()
        if name == "accounts":
            t.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = [
                {"id": "acc-1"}
            ]
        elif name == "portfolio_snapshots":
            t.select.return_value.eq.return_value.is_.return_value.order.return_value.limit.return_value.execute.return_value.data = [snap]
        elif name == "snapshot_holdings":
            t.select.return_value.eq.return_value.execute.return_value.data = [
                {"snapshot_id": "snap-x", "ticker": "NVDA", "quantity": 10,
                 "price": 1000, "market_value": 10_000,
                 "cost_basis": None, "unrealized_gain": None},
            ]
        elif name == "security_reference":
            t.select.return_value.in_.return_value.execute.return_value.data = [
                {"ticker": "NVDA", "asset_class": "equity", "sector": "Technology",
                 "region": "US", "look_through": None},
            ]
        else:
            # All other tables (transactions, user_notes, etc.) return empty
            # so that the KPI / other paths either get empty data or raise and
            # are caught by their own try/except guards.
            t.select.return_value.eq.return_value.execute.return_value.data = []
            t.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = []
        return t
    db.table.side_effect = table

    out = build_live_state_block(
        db=db, user_id="user-1",
        snapshot=_basic_snapshot(), goals=[],
        now=datetime(2026, 5, 7, tzinfo=timezone.utc),
    )
    assert "PORTFOLIO" in out
    assert "NVDA 100%" in out  # top holding
    assert "equity 100%" in out  # asset class breakdown
    assert "2026-05-01" in out  # latest snapshot date
    assert "portfolio_get_holdings" in out  # tool-routing hint
