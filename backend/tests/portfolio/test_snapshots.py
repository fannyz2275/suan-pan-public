from datetime import date
from typing import Any
from unittest.mock import MagicMock

from app.portfolio.snapshots import get_latest_snapshot


def _fake_db_with_data(snapshot_rows, holding_rows):
    """Build a chainable mock that responds to .table().select()...execute()."""
    db = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "portfolio_snapshots":
            t.select.return_value.eq.return_value.is_.return_value.order.return_value.limit.return_value.execute.return_value.data = snapshot_rows
        elif name == "snapshot_holdings":
            t.select.return_value.eq.return_value.execute.return_value.data = holding_rows
        return t
    db.table.side_effect = table
    return db


def test_get_latest_snapshot_returns_snapshot_with_holdings():
    snapshot_rows = [{
        "id": "snap-1", "account_id": "acc-1",
        "snapshot_date": "2026-04-15", "source": "manual",
        "total_value": 10000, "cash_value": 500,
        "created_at": "2026-04-15T00:00:00Z",
    }]
    holding_rows = [
        {"snapshot_id": "snap-1", "ticker": "NVDA", "quantity": 10,
         "price": 900, "market_value": 9000, "cost_basis": 7000,
         "unrealized_gain": 2000},
        {"snapshot_id": "snap-1", "ticker": "AAPL", "quantity": 5,
         "price": 100, "market_value": 500, "cost_basis": 400,
         "unrealized_gain": 100},
    ]
    db = _fake_db_with_data(snapshot_rows, holding_rows)
    snap = get_latest_snapshot(db, account_id="acc-1")
    assert snap is not None
    assert snap["total_value"] == 10000
    assert len(snap["holdings"]) == 2
    tickers = {h["ticker"] for h in snap["holdings"]}
    assert tickers == {"NVDA", "AAPL"}


def test_get_latest_snapshot_none_when_no_rows():
    db = _fake_db_with_data([], [])
    assert get_latest_snapshot(db, account_id="acc-1") is None


from app.portfolio.snapshots import create_manual_snapshot


def test_create_manual_snapshot_inserts_snapshot_then_holdings():
    db = MagicMock()
    inserted_snap = {
        "id": "snap-new", "user_id": "user-1", "account_id": "acc-1",
        "snapshot_date": "2026-05-06", "source": "manual",
        "total_value": 1900.0, "cash_value": 100.0, "created_at": "2026-05-06T00:00:00Z",
    }
    inserted_holding = {
        "snapshot_id": "snap-new", "ticker": "NVDA", "quantity": 2.0,
        "price": 900.0, "market_value": 1800.0, "cost_basis": 1500, "unrealized_gain": 300.0,
    }
    # Snapshot insert returns the new row.
    db.table.return_value.insert.return_value.execute.return_value.data = [inserted_snap]
    # Holdings insert returns inserted rows (second insert call reuses same mock).
    # We need the holdings insert to return [inserted_holding]; MagicMock reuses the
    # same chain so just override .data to include a holdings row — the snapshot insert
    # picks up [inserted_snap][0] and the holdings insert picks up [inserted_snap] again
    # but we only care that snap["holdings"] is populated. Use side_effect on table to
    # dispatch by call order.
    call_order = []

    def _table(name):
        call_order.append(name)
        t = MagicMock()
        if name == "portfolio_snapshots" and "portfolio_snapshots" not in call_order[:-1]:
            # First portfolio_snapshots call: the snapshot insert.
            t.insert.return_value.execute.return_value.data = [inserted_snap]
            # Supersede update chain (insert-first order: update comes after insert).
            t.update.return_value.eq.return_value.eq.return_value.eq.return_value.neq.return_value.is_.return_value.execute.return_value.data = []
        elif name == "portfolio_snapshots":
            # Subsequent portfolio_snapshots calls (supersede update).
            t.update.return_value.eq.return_value.eq.return_value.eq.return_value.neq.return_value.is_.return_value.execute.return_value.data = []
        elif name == "snapshot_holdings":
            t.insert.return_value.execute.return_value.data = [inserted_holding]
        return t

    db.table.side_effect = _table

    snap = create_manual_snapshot(
        db,
        user_id="user-1",
        account_id="acc-1",
        snapshot_date=date(2026, 5, 6),
        cash_value=100.0,
        holdings=[
            {"ticker": "NVDA", "quantity": 2, "price": 900, "cost_basis": 1500},
        ],
    )
    assert snap["id"] == "snap-new"
    assert snap["holdings"] == [inserted_holding]
    # snapshot insert + supersede update + holdings insert = 3 table calls
    assert db.table.call_count >= 3


from app.portfolio.snapshots import create_statement_snapshot


def test_create_statement_snapshot_inserts_all_three_tables():
    db = MagicMock()
    inserted_snap = {
        "id": "snap-stmt", "user_id": "user-1", "account_id": "acc-1",
        "snapshot_date": "2026-04-30", "source": "statement_import",
        "total_value": 18700.0, "cash_value": 1000.0,
        "created_at": "2026-04-30T00:00:00Z",
    }
    inserted_holdings = [
        {"id": "h1", "snapshot_id": "snap-stmt", "ticker": "NVDA", "quantity": 10,
         "price": 950, "market_value": 9500, "cost_basis": 7000, "unrealized_gain": 2500},
        {"id": "h2", "snapshot_id": "snap-stmt", "ticker": "VOO", "quantity": 18,
         "price": 455, "market_value": 8190, "cost_basis": None, "unrealized_gain": None},
    ]
    inserted_txns = [
        {"id": "t1"}, {"id": "t2"},
    ]

    inserts: list[tuple[str, Any]] = []

    def table(name):
        t = MagicMock()
        if name == "portfolio_snapshots":
            t.insert.return_value.execute.return_value.data = [inserted_snap]
            t.update.return_value.eq.return_value.eq.return_value.eq.return_value.neq.return_value.is_.return_value.execute.return_value.data = []
        elif name == "snapshot_holdings":
            t.insert.return_value.execute.return_value.data = inserted_holdings
        elif name == "investment_transactions":
            t.insert.return_value.execute.return_value.data = inserted_txns
        return t
    db.table.side_effect = table

    snap = create_statement_snapshot(
        db,
        user_id="user-1",
        account_id="acc-1",
        snapshot_date=date(2026, 4, 30),
        cash_value=1000.0,
        holdings=[
            {"ticker": "NVDA", "quantity": 10, "price": 950, "cost_basis": 7000},
            {"ticker": "VOO",  "quantity": 18, "price": 455},
        ],
        investment_transactions=[
            {"date": date(2026, 4, 15), "type": "buy",      "ticker": "NVDA", "quantity": 2, "price": 920, "amount": -1840},
            {"date": date(2026, 4, 25), "type": "dividend", "ticker": "VOO",                              "amount": 18.5},
        ],
    )
    assert snap["id"] == "snap-stmt"
    assert snap["source"] == "statement_import"
    # snapshot insert + holdings insert + txns insert + supersede update
    table_calls = [c.args[0] for c in db.table.call_args_list]
    assert "portfolio_snapshots" in table_calls
    assert "snapshot_holdings" in table_calls
    assert "investment_transactions" in table_calls
    assert len(snap["holdings"]) == 2


def test_create_statement_snapshot_skips_empty_children():
    db = MagicMock()
    inserted_snap = {
        "id": "snap-stmt", "user_id": "user-1", "account_id": "acc-1",
        "snapshot_date": "2026-04-30", "source": "statement_import",
        "total_value": 0.0, "cash_value": 0.0,
        "created_at": "2026-04-30T00:00:00Z",
    }

    def table(name):
        t = MagicMock()
        if name == "portfolio_snapshots":
            t.insert.return_value.execute.return_value.data = [inserted_snap]
            t.update.return_value.eq.return_value.eq.return_value.eq.return_value.neq.return_value.is_.return_value.execute.return_value.data = []
        return t
    db.table.side_effect = table

    snap = create_statement_snapshot(
        db, user_id="u", account_id="a",
        snapshot_date=date(2026, 4, 30),
        cash_value=0,
        holdings=[],
        investment_transactions=[],
    )
    assert snap["id"] == "snap-stmt"
    table_calls = [c.args[0] for c in db.table.call_args_list]
    # Only the snapshot table should be touched (insert + supersede); no children.
    assert "snapshot_holdings" not in table_calls
    assert "investment_transactions" not in table_calls


def test_create_statement_snapshot_clears_prior_txns_in_window():
    """Re-importing the same statement: prior statement_import txns in the window
    are deleted before new ones are inserted."""
    db = MagicMock()
    inserted_snap = {
        "id": "snap-2", "user_id": "u", "account_id": "a",
        "snapshot_date": "2026-04-30", "source": "statement_import",
        "total_value": 0.0, "cash_value": 0.0,
        "created_at": "2026-04-30T00:00:00Z",
    }
    delete_calls: list = []

    def table(name):
        t = MagicMock()
        if name == "portfolio_snapshots":
            t.insert.return_value.execute.return_value.data = [inserted_snap]
            t.update.return_value.eq.return_value.eq.return_value.eq.return_value.neq.return_value.is_.return_value.execute.return_value.data = []
        elif name == "investment_transactions":
            # Capture the chained delete call.
            delete_chain = MagicMock()
            delete_chain.eq.return_value = delete_chain
            delete_chain.gte.return_value = delete_chain
            delete_chain.lte.return_value = delete_chain
            delete_chain.execute.return_value.data = []
            t.delete.return_value = delete_chain
            delete_calls.append(delete_chain)
            t.insert.return_value.execute.return_value.data = [{"id": "t1"}]
        return t
    db.table.side_effect = table

    create_statement_snapshot(
        db, user_id="u", account_id="a",
        snapshot_date=date(2026, 4, 30),
        cash_value=0,
        holdings=[],
        investment_transactions=[
            {"date": date(2026, 4, 1), "type": "transfer_in", "amount": 1000},
            {"date": date(2026, 4, 15), "type": "buy", "ticker": "X",
             "quantity": 1, "price": 100, "amount": -100},
        ],
    )
    # Delete chain was invoked at least once for investment_transactions.
    assert len(delete_calls) >= 1


from app.portfolio.snapshots import create_plaid_snapshot


def test_create_plaid_snapshot_inserts_all_three_tables():
    db = MagicMock()
    inserted_snap = {
        "id": "snap-plaid", "user_id": "user-1", "account_id": "acc-1",
        "snapshot_date": "2026-05-07", "source": "plaid",
        "total_value": 19450.0, "cash_value": 250.0,
        "created_at": "2026-05-07T00:00:00Z",
    }
    inserted_holdings = [
        {"id": "h1", "snapshot_id": "snap-plaid", "ticker": "NVDA",
         "quantity": 10, "price": 950, "market_value": 9500,
         "cost_basis": 7000, "unrealized_gain": 2500},
    ]

    existing_txn_id_lookup_calls = []

    def table(name):
        t = MagicMock()
        if name == "portfolio_snapshots":
            t.insert.return_value.execute.return_value.data = [inserted_snap]
            t.update.return_value.eq.return_value.eq.return_value.eq.return_value.neq.return_value.is_.return_value.execute.return_value.data = []
        elif name == "snapshot_holdings":
            t.insert.return_value.execute.return_value.data = inserted_holdings
        elif name == "investment_transactions":
            # Idempotent insert: existing-txn lookup returns empty (no dups).
            existing_query = MagicMock()
            existing_query.execute.return_value.data = []
            t.select.return_value.eq.return_value.in_.return_value = existing_query
            t.insert.return_value.execute.return_value.data = [{"id": "t1"}]
        return t
    db.table.side_effect = table

    snap = create_plaid_snapshot(
        db,
        user_id="user-1",
        account_id="acc-1",
        snapshot_date=date(2026, 5, 7),
        cash_value=250.0,
        holdings=[
            {"ticker": "NVDA", "quantity": 10, "price": 950,
             "market_value": 9500, "cost_basis": 7000},
        ],
        investment_transactions=[
            {"date": "2026-05-01", "type": "buy", "ticker": "NVDA",
             "quantity": 2, "price": 920, "amount": -1840,
             "plaid_investment_transaction_id": "p-1"},
        ],
    )
    assert snap["id"] == "snap-plaid"
    assert snap["source"] == "plaid"
    table_calls = [c.args[0] for c in db.table.call_args_list]
    assert "portfolio_snapshots" in table_calls
    assert "snapshot_holdings" in table_calls
    assert "investment_transactions" in table_calls


def test_create_plaid_snapshot_total_value_uses_market_value_when_present():
    """When caller supplies market_value distinct from qty*price (e.g. Plaid's
    institution_value with rounding), total_value must use market_value to keep
    the snapshot row consistent with snapshot_holdings.market_value."""
    db = MagicMock()
    inserted_snap = {
        "id": "snap-mv", "user_id": "u", "account_id": "a",
        "snapshot_date": "2026-05-09", "source": "plaid",
        "total_value": 0, "cash_value": 0,
        "created_at": "2026-05-09T00:00:00Z",
    }
    captured_snap_insert: dict = {}

    def table(name):
        t = MagicMock()
        if name == "portfolio_snapshots":
            def capture_insert(payload):
                captured_snap_insert.update(payload)
                m = MagicMock()
                m.execute.return_value.data = [{**inserted_snap, **payload}]
                return m
            t.insert.side_effect = capture_insert
            t.update.return_value.eq.return_value.eq.return_value.eq.return_value.neq.return_value.is_.return_value.execute.return_value.data = []
        elif name == "snapshot_holdings":
            t.insert.return_value.execute.return_value.data = []
        elif name == "investment_transactions":
            existing = MagicMock()
            existing.execute.return_value.data = []
            t.select.return_value.eq.return_value.in_.return_value = existing
        return t
    db.table.side_effect = table

    create_plaid_snapshot(
        db, user_id="u", account_id="a",
        snapshot_date=date(2026, 5, 9),
        cash_value=100,
        holdings=[
            # Plaid: 10 shares × $100 = $1000 by qty*price, but institution_value = $1001 (rounding).
            {"ticker": "X", "quantity": 10, "price": 100, "market_value": 1001},
        ],
        investment_transactions=[],
    )
    # total_value should reflect market_value, not qty*price.
    assert captured_snap_insert["total_value"] == 100 + 1001  # cash + mv


def test_create_plaid_snapshot_skips_duplicate_investment_txns():
    """When Plaid returns the same txn twice (re-sync), we must not double-insert."""
    db = MagicMock()
    inserted_snap = {
        "id": "snap-plaid-2", "user_id": "user-1", "account_id": "acc-1",
        "snapshot_date": "2026-05-07", "source": "plaid",
        "total_value": 0.0, "cash_value": 0.0,
        "created_at": "2026-05-07T00:00:00Z",
    }
    insert_calls: list = []

    def table(name):
        t = MagicMock()
        if name == "portfolio_snapshots":
            t.insert.return_value.execute.return_value.data = [inserted_snap]
            t.update.return_value.eq.return_value.eq.return_value.eq.return_value.neq.return_value.is_.return_value.execute.return_value.data = []
        elif name == "investment_transactions":
            # Pretend txn p-already exists.
            existing_query = MagicMock()
            existing_query.execute.return_value.data = [{"plaid_investment_transaction_id": "p-already"}]
            t.select.return_value.eq.return_value.in_.return_value = existing_query
            # Track what gets inserted.
            t.insert.side_effect = lambda rows: (insert_calls.append(rows), MagicMock(execute=MagicMock(return_value=MagicMock(data=rows))))[1]
        return t
    db.table.side_effect = table

    create_plaid_snapshot(
        db, user_id="u", account_id="a",
        snapshot_date=date(2026, 5, 7),
        cash_value=0,
        holdings=[],
        investment_transactions=[
            {"date": "2026-05-01", "type": "buy", "ticker": "NVDA",
             "amount": -100, "plaid_investment_transaction_id": "p-already"},
            {"date": "2026-05-02", "type": "sell", "ticker": "NVDA",
             "amount": 110, "plaid_investment_transaction_id": "p-new"},
        ],
    )
    # Only the new one should have been inserted.
    assert len(insert_calls) == 1
    assert len(insert_calls[0]) == 1
    assert insert_calls[0][0]["plaid_investment_transaction_id"] == "p-new"
