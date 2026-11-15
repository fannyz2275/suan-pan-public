"""Spec B portfolio invariants.

I1 — Attribution identity (Phase 1).
I5 — Snapshot total consistency (Phase 3).
I6 — Statement import tie-out (Phase 3).
I10 — Cost-basis subset (Phase 3).
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings

from app.portfolio.attribution import compute_attribution
from app.portfolio.snapshots import create_manual_snapshot
from app.portfolio.statement_parser import parse_investment_statement

from .strategies import attribution_transactions, period_value


# Tolerance accounts for compute_attribution rounding each bucket to 2dp.
_IDENTITY_ABS = 0.06


def _identity_residual(decomp: dict) -> float:
    lhs = decomp["end_value"] - decomp["start_value"]
    rhs = (
        decomp["contributions"]
        + decomp["withdrawals"]
        + decomp["dividends"]
        + decomp["trades"]
        + decomp["market"]
        + decomp["unattributed"]
    )
    return lhs - rhs


def test_attribution_identity_known_fixture():
    """Hand-computed: only contributions and dividends, market absorbs residual."""
    decomp = compute_attribution(
        start_value=10_000.0,
        end_value=11_500.0,
        transactions=[
            {"type": "transfer_in", "amount": 1_000.0},
            {"type": "dividend", "amount": 50.0},
        ],
    )
    assert decomp["contributions"] == pytest.approx(1_000.0, abs=1e-9)
    assert decomp["dividends"] == pytest.approx(50.0, abs=1e-9)
    # market absorbs residual since no clean_market_estimate provided
    assert decomp["unattributed"] == pytest.approx(0.0, abs=1e-9)
    assert _identity_residual(decomp) == pytest.approx(0.0, abs=_IDENTITY_ABS)


def test_attribution_identity_unattributed_residual():
    """When clean_market_estimate is supplied, unattributed picks up the leftover."""
    decomp = compute_attribution(
        start_value=10_000.0,
        end_value=11_500.0,
        transactions=[{"type": "dividend", "amount": 50.0}],
        clean_market_estimate=1_400.0,
    )
    assert decomp["market"] == pytest.approx(1_400.0, abs=1e-9)
    assert decomp["unattributed"] == pytest.approx(50.0, abs=_IDENTITY_ABS)
    assert _identity_residual(decomp) == pytest.approx(0.0, abs=_IDENTITY_ABS)


@given(
    start_value=period_value,
    end_value=period_value,
    transactions=attribution_transactions,
)
@settings(suppress_health_check=[HealthCheck.too_slow])
def test_attribution_identity_property(start_value, end_value, transactions):
    """Identity holds for arbitrary transaction lists (hypothesis-driven)."""
    decomp = compute_attribution(
        start_value=start_value,
        end_value=end_value,
        transactions=transactions,
    )
    assert _identity_residual(decomp) == pytest.approx(0.0, abs=_IDENTITY_ABS)


# ---------------------------------------------------------------------------
# I5 — Snapshot total consistency
#   snap.total_value == snap.cash_value + Σ(holding.market_value)
# ---------------------------------------------------------------------------

def _capture_insert_payloads():
    """Helper: returns (db, captured) where `captured["snapshot"]`/`captured["holdings"]`
    record the insert payloads sent through the MagicMock DB."""
    captured: dict = {"snapshot": None, "holdings": None}

    def _make_table(name: str) -> MagicMock:
        t = MagicMock()
        if name == "portfolio_snapshots":
            def _capture_snap_insert(payload):
                captured["snapshot"] = payload
                inserted = MagicMock()
                inserted.execute.return_value.data = [{
                    **payload,
                    "id": "snap-id",
                    "created_at": "2026-05-09T00:00:00Z",
                    "source": payload.get("source", "manual"),
                }]
                return inserted

            t.insert.side_effect = _capture_snap_insert
            t.update.return_value.eq.return_value.eq.return_value.eq.return_value.neq.return_value.is_.return_value.execute.return_value.data = []
        elif name == "snapshot_holdings":
            def _capture_holdings_insert(rows):
                captured["holdings"] = rows
                inserted = MagicMock()
                inserted.execute.return_value.data = rows
                return inserted

            t.insert.side_effect = _capture_holdings_insert
        return t

    db = MagicMock()
    db.table.side_effect = _make_table
    return db, captured


def test_invariant_i5_snapshot_total_consistency():
    """create_manual_snapshot must persist total_value == cash + Σ(holding mv)."""
    db, captured = _capture_insert_payloads()
    holdings = [
        {"ticker": "NVDA", "quantity": 10, "price": 800.0, "cost_basis": 6_000},
        {"ticker": "AAPL", "quantity": 5, "price": 200.0, "cost_basis": 850.0},
    ]
    create_manual_snapshot(
        db,
        user_id="u-test",
        account_id="acc-1",
        snapshot_date=date(2026, 5, 1),
        cash_value=500.0,
        holdings=holdings,
    )
    snap = captured["snapshot"]
    holdings_rows = captured["holdings"]
    expected_total = snap["cash_value"] + sum(
        float(h["market_value"]) for h in holdings_rows
    )
    assert snap["total_value"] == pytest.approx(expected_total, rel=1e-6)


def test_invariant_i5_cash_only_account():
    """Edge case: zero holdings, cash only — total_value still consistent."""
    db, captured = _capture_insert_payloads()
    create_manual_snapshot(
        db,
        user_id="u-test",
        account_id="acc-1",
        snapshot_date=date(2026, 5, 1),
        cash_value=10_000.0,
        holdings=[],
    )
    snap = captured["snapshot"]
    assert snap["total_value"] == pytest.approx(snap["cash_value"], rel=1e-6)


# ---------------------------------------------------------------------------
# I6 — Statement import tie-out
#   cash_value + Σ(qty × price) ≈ total_value_reported within 1%
# ---------------------------------------------------------------------------

def _fake_gemini(text: str) -> MagicMock:
    client = MagicMock()
    client.models.generate_content.return_value.text = text
    return client


def test_invariant_i6_statement_tie_out_within_1_percent():
    response = """
    {
      "statement_date": "2026-04-30",
      "cash_value": 1234.56,
      "total_value_reported": 11234.56,
      "holdings": [
        {"ticker": "NVDA", "quantity": 10, "price": 1000, "market_value": 10000}
      ],
      "investment_transactions": []
    }
    """
    with patch(
        "app.portfolio.statement_parser.gemini_client",
        return_value=_fake_gemini(response),
    ):
        parsed = parse_investment_statement("ignored")

    assert parsed["total_value_reported"] is not None
    computed = parsed["cash_value"] + sum(
        float(h["quantity"]) * float(h["price"]) for h in parsed["holdings"]
    )
    ratio = abs(computed - parsed["total_value_reported"]) / parsed["total_value_reported"]
    assert ratio <= 0.01


def test_invariant_i6_skipped_when_total_not_reported():
    """When parser returns no total_value_reported, the invariant is N/A."""
    response = """
    {"statement_date": "2026-04-30", "cash_value": 0,
     "holdings": [{"ticker": "NVDA", "quantity": 1, "price": 100, "market_value": 100}],
     "investment_transactions": []}
    """
    with patch(
        "app.portfolio.statement_parser.gemini_client",
        return_value=_fake_gemini(response),
    ):
        parsed = parse_investment_statement("ignored")

    assert parsed["total_value_reported"] is None  # invariant doesn't apply


# ---------------------------------------------------------------------------
# I10 — Cost-basis subset
#   When cost_basis is present: unrealized_gain == market_value - cost_basis
#   When cost_basis is null:    unrealized_gain is null
# ---------------------------------------------------------------------------

def test_invariant_i10_cost_basis_subset_present_and_null():
    db, captured = _capture_insert_payloads()
    holdings = [
        {"ticker": "NVDA", "quantity": 10, "price": 800.0, "cost_basis": 6_000.0},
        {"ticker": "AAPL", "quantity": 5, "price": 200.0, "cost_basis": None},
    ]
    create_manual_snapshot(
        db,
        user_id="u-test",
        account_id="acc-1",
        snapshot_date=date(2026, 5, 1),
        cash_value=0.0,
        holdings=holdings,
    )
    holdings_rows = captured["holdings"]
    by_ticker = {h["ticker"]: h for h in holdings_rows}

    nvda = by_ticker["NVDA"]
    assert nvda["unrealized_gain"] == pytest.approx(
        nvda["market_value"] - nvda["cost_basis"], abs=0.01
    )

    aapl = by_ticker["AAPL"]
    assert aapl["cost_basis"] is None
    assert aapl["unrealized_gain"] is None


# ---------------------------------------------------------------------------
# I8 — Plaid sign convention
#
# Plaid sends positive amounts for cash-out transactions. Our schema stores
# signed cash impact (positive = cash IN). Therefore after mapping:
#   buy / fee / transfer_out  → negative
#   sell / dividend / interest / transfer_in → positive
# Net cash flow for the period == sum of all mapped amounts.
# ---------------------------------------------------------------------------

from app.portfolio.plaid_sync import map_plaid_investment_transactions


def _plaid_securities() -> list[dict]:
    return [
        {"security_id": "sec-nvda", "ticker_symbol": "NVDA",
         "name": "NVIDIA", "type": "equity"},
    ]


def _plaid_txn(*, type_: str, subtype: str | None, amount: float, **extras) -> dict:
    return {
        "account_id": "plaid-acc-1",
        "investment_transaction_id": f"itx-{type_}-{amount}",
        "type": type_,
        "subtype": subtype,
        "amount": amount,
        "date": "2026-04-15",
        "security_id": "sec-nvda",
        "quantity": extras.get("quantity"),
        "price": extras.get("price"),
    }


def test_invariant_i8_cash_out_types_are_negative_after_mapping():
    """Plaid's positive-cash-out amounts get flipped to negative."""
    plaid_txns = [
        _plaid_txn(type_="buy", subtype=None, amount=1_000),         # cash out
        _plaid_txn(type_="fee", subtype=None, amount=10),            # cash out
        _plaid_txn(type_="transfer", subtype="withdrawal", amount=500),  # cash out
    ]
    out = map_plaid_investment_transactions(plaid_txns, _plaid_securities())
    by_kind = {t["type"]: t for t in out["plaid-acc-1"]}
    assert by_kind["buy"]["amount"] == -1_000
    assert by_kind["fee"]["amount"] == -10
    assert by_kind["transfer_out"]["amount"] == -500


def test_invariant_i8_cash_in_types_keep_sign_after_mapping():
    """sell / dividend / interest / transfer_in stay positive."""
    plaid_txns = [
        _plaid_txn(type_="sell", subtype=None, amount=2_500),
        _plaid_txn(type_="cash", subtype="dividend", amount=120),
        _plaid_txn(type_="cash", subtype="interest", amount=30),
        _plaid_txn(type_="transfer", subtype="deposit", amount=5_000),
    ]
    out = map_plaid_investment_transactions(plaid_txns, _plaid_securities())
    by_kind = {t["type"]: t for t in out["plaid-acc-1"]}
    assert by_kind["sell"]["amount"] == 2_500
    assert by_kind["dividend"]["amount"] == 120
    assert by_kind["interest"]["amount"] == 30
    assert by_kind["transfer_in"]["amount"] == 5_000


def test_invariant_i8_net_cash_flow_matches_signed_sum():
    """Net cash flow for the period == Σ(amount for cash-in) − Σ(|amount| for cash-out)."""
    plaid_txns = [
        _plaid_txn(type_="transfer", subtype="deposit", amount=5_000),  # +5000
        _plaid_txn(type_="cash", subtype="dividend", amount=120),       # +120
        _plaid_txn(type_="buy", subtype=None, amount=2_000),            # -2000
        _plaid_txn(type_="fee", subtype=None, amount=10),               # -10
        _plaid_txn(type_="transfer", subtype="withdrawal", amount=500), # -500
    ]
    out = map_plaid_investment_transactions(plaid_txns, _plaid_securities())
    rows = out["plaid-acc-1"]

    # Spec formula: cash_in - cash_out_abs
    cash_in = sum(t["amount"] for t in rows if t["type"] in {"transfer_in", "dividend", "interest", "sell"})
    cash_out_abs = sum(abs(t["amount"]) for t in rows if t["type"] in {"transfer_out", "buy", "fee"})
    expected_net = cash_in - cash_out_abs

    # All amounts are signed cash impact, so signed sum == expected net.
    actual_net = sum(t["amount"] for t in rows)
    assert actual_net == pytest.approx(expected_net, abs=1e-6)
    assert actual_net == pytest.approx(2_610.0, abs=1e-6)


def test_invariant_i8_already_negative_amounts_pass_through():
    """If Plaid returns a negative amount on a buy (rare but possible), we don't
    double-flip — the net is still cash out."""
    plaid_txns = [_plaid_txn(type_="buy", subtype=None, amount=-1_000)]
    out = map_plaid_investment_transactions(plaid_txns, _plaid_securities())
    assert out["plaid-acc-1"][0]["amount"] == -1_000
