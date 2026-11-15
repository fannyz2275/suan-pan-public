"""
Unit tests for the Seed deterministic fixture builder.

TDD red-phase: these tests are written before the implementation.
All tests use inline imports matching the project's red-phase pattern.
"""

import pytest
from datetime import date
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Test 1: every with_* returns self for chaining
# ---------------------------------------------------------------------------

def test_seed_chain_returns_self():
    from tests.evals.shared.seed import Seed

    s = Seed()
    assert s.with_user("u-chain") is s
    assert s.with_account(name="Brokerage", type="brokerage", balance=1000.0) is s
    assert s.with_security(ticker="NVDA", asset_class="equity", sector="Technology") is s
    assert s.with_snapshot(
        account_id="acc-brokerage",
        snapshot_date=date(2026, 4, 1),
        cash_value=500.0,
        holdings=[{"ticker": "NVDA", "quantity": 10, "price": 120.0}],
    ) is s
    assert s.with_investment_txn(
        account_id="acc-brokerage",
        date=date(2026, 3, 15),
        type="buy",
        ticker="NVDA",
        quantity=10,
        price=120.0,
        amount=-1200.0,
    ) is s
    assert s.with_goal(
        name="Emergency Fund",
        type="savings",
        target_amount=20000.0,
        target_date=date(2027, 1, 1),
    ) is s


# ---------------------------------------------------------------------------
# Helper: build a mock DB whose .table().upsert/insert().execute() chain works
# ---------------------------------------------------------------------------

def _make_mock_db():
    """Returns a MagicMock db whose .table().upsert/insert().execute() chain works."""
    db = MagicMock()
    table_mock = MagicMock()
    db.table.return_value = table_mock
    table_mock.upsert.return_value = table_mock
    table_mock.insert.return_value = table_mock
    table_mock.execute.return_value = MagicMock(data=[{"id": "returned-id"}])
    return db


# ---------------------------------------------------------------------------
# Test 2: apply() writes user, account, snapshot, and holdings to the DB
# ---------------------------------------------------------------------------

def test_seed_apply_writes_user_account_snapshot_holdings():
    from tests.evals.shared.seed import Seed, AppliedSeed

    db = _make_mock_db()

    result = (
        Seed()
        .with_user("u-001")
        .with_account(name="My Brokerage", type="brokerage", balance=5000.0)
        .with_snapshot(
            account_id="acc-my-brokerage",
            snapshot_date=date(2026, 4, 1),
            cash_value=200.0,
            holdings=[
                {"ticker": "NVDA", "quantity": 5, "price": 100.0},
                {"ticker": "VOO", "quantity": 2, "price": 450.0},
            ],
        )
        .apply(db)
    )

    # result must be an AppliedSeed
    assert isinstance(result, AppliedSeed)
    assert result.user_id == "u-001"
    assert "My Brokerage" in result.account_ids
    assert len(result.snapshot_ids) == 1

    # The DB must be called for the right table names
    table_names_called = [c.args[0] for c in db.table.call_args_list]
    assert "profiles" in table_names_called
    assert "accounts" in table_names_called
    assert "portfolio_snapshots" in table_names_called
    assert "snapshot_holdings" in table_names_called


# ---------------------------------------------------------------------------
# Test 3: calling apply() twice on a fresh DB produces same call count (idempotent via upsert)
# ---------------------------------------------------------------------------

def test_seed_apply_idempotent():
    """Seed uses upsert, so calling apply() twice should make the same number of DB operations."""
    from tests.evals.shared.seed import Seed

    seed = (
        Seed()
        .with_user("u-idem")
        .with_account(name="Savings", type="savings", balance=1000.0)
    )

    db1 = _make_mock_db()
    seed.apply(db1)
    first_call_count = db1.table.call_count

    db2 = _make_mock_db()
    seed.apply(db2)
    second_call_count = db2.table.call_count

    # Both apply() calls must make the exact same number of table operations
    assert first_call_count == second_call_count, (
        f"First apply made {first_call_count} table calls, "
        f"second made {second_call_count} — not idempotent"
    )


# ---------------------------------------------------------------------------
# Test 4: total_value is computed from cash_value + Σ(qty × price) when not provided
# ---------------------------------------------------------------------------

def test_seed_compute_total_value_from_holdings():
    """When total_value is not supplied, Seed auto-derives it from cash + holdings."""
    from tests.evals.shared.seed import Seed

    captured_snapshots = []

    db = MagicMock()

    def capture_table(name):
        m = MagicMock()
        if name == "portfolio_snapshots":
            def upsert_capture(payload, **kwargs):
                captured_snapshots.append(payload)
                return m
            m.upsert = upsert_capture
        else:
            m.upsert.return_value = m
            m.insert.return_value = m
        m.execute.return_value = MagicMock(data=[{"id": "snap-id-001"}])
        return m

    db.table.side_effect = capture_table

    (
        Seed()
        .with_user("u-tv")
        .with_account(name="Brokerage TV", type="brokerage", balance=0)
        .with_snapshot(
            account_id="acc-brokerage-tv",
            snapshot_date=date(2026, 4, 1),
            cash_value=500.0,
            holdings=[
                {"ticker": "AAPL", "quantity": 10, "price": 150.0},   # 1500
                {"ticker": "MSFT", "quantity": 5, "price": 300.0},    # 1500
            ],
        )
        .apply(db)
    )

    # cash(500) + AAPL(1500) + MSFT(1500) = 3500
    assert len(captured_snapshots) == 1
    assert captured_snapshots[0]["total_value"] == pytest.approx(3500.0)


# ---------------------------------------------------------------------------
# Test 5: default market_value on a holding is qty × price
# ---------------------------------------------------------------------------

def test_seed_default_market_value_is_qty_times_price():
    """If market_value is absent from a holding dict, Seed inserts quantity * price."""
    from tests.evals.shared.seed import Seed

    captured_holdings = []

    db = MagicMock()

    def capture_table(name):
        m = MagicMock()
        if name == "snapshot_holdings":
            def insert_capture(payload):
                if isinstance(payload, list):
                    captured_holdings.extend(payload)
                else:
                    captured_holdings.append(payload)
                return m
            m.insert = insert_capture
        else:
            m.upsert.return_value = m
            m.insert.return_value = m
        m.execute.return_value = MagicMock(data=[{"id": "holding-id"}])
        return m

    db.table.side_effect = capture_table

    (
        Seed()
        .with_user("u-mv")
        .with_account(name="Brokerage MV", type="brokerage", balance=0)
        .with_snapshot(
            account_id="acc-brokerage-mv",
            snapshot_date=date(2026, 4, 1),
            cash_value=0.0,
            holdings=[
                # No market_value supplied — should default to 3 * 200 = 600
                {"ticker": "TSLA", "quantity": 3, "price": 200.0},
            ],
        )
        .apply(db)
    )

    assert len(captured_holdings) >= 1
    tsla = next(h for h in captured_holdings if h["ticker"] == "TSLA")
    assert tsla["market_value"] == pytest.approx(600.0)
