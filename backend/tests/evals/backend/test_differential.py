"""Spec B differential MCP↔REST equality.

D1: holdings (Phase 1).
D2: exposure (Phase 3).
D3: attribution + macro context (Phase 3).
"""
from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from app.mcp.tools import (
    portfolio_get_attribution,
    portfolio_get_exposure,
    portfolio_get_holdings,
)
from app.portfolio.router import (
    get_attribution,
    get_exposure,
    get_holdings,
)


ACCOUNT_ID = "11111111-1111-1111-1111-111111111111"
USER_ID = "u-test"

_FIXTURE_HOLDINGS = [
    {
        "ticker": "NVDA",
        "quantity": 10,
        "price": 820.0,
        "market_value": 8_200.0,
        "cost_basis": 6_000.0,
        "unrealized_gain": 2_200.0,
    },
    {
        "ticker": "AAPL",
        "quantity": 5,
        "price": 200.0,
        "market_value": 1_000.0,
        "cost_basis": 850.0,
        "unrealized_gain": 150.0,
    },
]


def _fake_snapshot() -> dict:
    return {
        "id": "snap-1",
        "account_id": ACCOUNT_ID,
        "snapshot_date": "2026-05-01",
        "source": "manual",
        "total_value": 9_200.0,
        "cash_value": 0.0,
        "holdings": [dict(h) for h in _FIXTURE_HOLDINGS],
    }


def test_holdings_differential_mcp_vs_rest():
    """MCP and REST surfaces agree on every per-ticker holding (within 2dp on percent)."""
    fake_db = MagicMock()
    fake_user = MagicMock()
    fake_user.id = UUID(int=1)

    # Path A: MCP call. Patch helpers it depends on.
    with patch(
        "app.mcp.tools._user_owns_investment_account", return_value=True
    ), patch(
        "app.portfolio.snapshots.get_latest_snapshot",
        return_value=_fake_snapshot(),
    ):
        mcp_result = portfolio_get_holdings(
            fake_db, USER_ID, account_id=ACCOUNT_ID
        )

    # Path B: REST handler. Bypass HTTP — call the function directly.
    with patch(
        "app.portfolio.router.get_admin_db", return_value=fake_db
    ), patch(
        "app.portfolio.router._assert_owns_account"
    ), patch(
        "app.portfolio.router.snapshots.ensure_today_snapshot"
    ), patch(
        "app.portfolio.router.snapshots.get_latest_snapshot",
        return_value=_fake_snapshot(),
    ):
        rest_models = asyncio.run(
            get_holdings(account_id=UUID(ACCOUNT_ID), user=fake_user)
        )

    rest_result = [m.model_dump() for m in rest_models]

    # Both surfaces must return one row per ticker, sorted by market_value desc.
    assert [h["ticker"] for h in mcp_result] == [h["ticker"] for h in rest_result]

    for mcp_h, rest_h in zip(
        sorted(mcp_result, key=lambda h: h["ticker"]),
        sorted(rest_result, key=lambda h: h["ticker"]),
    ):
        assert mcp_h["ticker"] == rest_h["ticker"]
        assert mcp_h["quantity"] == pytest.approx(rest_h["quantity"], rel=1e-6)
        assert mcp_h["market_value"] == pytest.approx(
            rest_h["market_value"], rel=1e-6
        )
        # Known difference: MCP rounds percent to 2dp, REST to 4dp.
        # Assert 2dp agreement per spec D1.
        assert round(mcp_h["percent"], 2) == round(rest_h["percent"], 2)
        assert mcp_h["cost_basis"] == rest_h["cost_basis"]


def test_holdings_error_parity_on_unowned_account():
    """Both surfaces refuse to serve data for an unowned account, with documented shapes."""
    from fastapi import HTTPException

    fake_db = MagicMock()
    fake_user = MagicMock()
    fake_user.id = UUID(int=1)
    other_uuid = "22222222-2222-2222-2222-222222222222"

    # MCP: _user_owns_investment_account → False → returns [{"error": "..."}]
    with patch(
        "app.mcp.tools._user_owns_investment_account", return_value=False
    ):
        mcp_result = portfolio_get_holdings(
            fake_db, USER_ID, account_id=other_uuid
        )
    assert mcp_result == [{"error": "account not found"}]

    # REST: _assert_owns_account raises HTTPException(404)
    def _raise_404(*args, **kwargs):
        raise HTTPException(404, "account not found")

    with patch(
        "app.portfolio.router.get_admin_db", return_value=fake_db
    ), patch(
        "app.portfolio.router.snapshots.ensure_today_snapshot"
    ), patch(
        "app.portfolio.router._assert_owns_account", side_effect=_raise_404
    ):
        with pytest.raises(HTTPException) as rest_exc:
            asyncio.run(
                get_holdings(account_id=UUID(other_uuid), user=fake_user)
            )
        assert rest_exc.value.status_code == 404

    # Shapes differ (list-with-error vs HTTPException) but both surfaces fail —
    # which is the semantic guarantee D4 requires.


# ---------------------------------------------------------------------------
# D2 — Exposure (MCP vs REST)
# ---------------------------------------------------------------------------

def _exposure_snapshot() -> dict:
    return {
        "id": "snap-1",
        "account_id": ACCOUNT_ID,
        "snapshot_date": "2026-05-01",
        "source": "manual",
        "total_value": 10_000,
        "cash_value": 0,
        "created_at": "2026-05-01T00:00:00Z",
        "holdings": [
            {"ticker": "NVDA", "quantity": 10, "price": 900,
             "market_value": 9_000, "cost_basis": None, "unrealized_gain": None},
            {"ticker": "BND", "quantity": 5, "price": 200,
             "market_value": 1_000, "cost_basis": None, "unrealized_gain": None},
        ],
    }


def _ref_rows() -> list[dict]:
    return [
        {"ticker": "NVDA", "asset_class": "equity", "sector": "Technology",
         "region": "US", "look_through": None},
        {"ticker": "BND", "asset_class": "fixed_income", "sector": None,
         "region": "US", "look_through": None},
    ]


def test_exposure_differential_mcp_vs_rest():
    """MCP `portfolio_get_exposure` and REST `get_exposure` agree per slice."""
    fake_user = MagicMock()
    fake_user.id = UUID(int=1)

    # MCP path
    mcp_db = MagicMock()
    mcp_db.table.return_value.select.return_value.in_.return_value.execute.return_value.data = (
        _ref_rows()
    )
    with patch(
        "app.mcp.tools._user_owns_investment_account", return_value=True
    ), patch(
        "app.portfolio.snapshots.get_latest_snapshot",
        return_value=_exposure_snapshot(),
    ):
        mcp_slices = portfolio_get_exposure(
            mcp_db, USER_ID, dimension="asset_class", account_id=ACCOUNT_ID
        )

    # REST path
    rest_db = MagicMock()
    rest_db.table.return_value.select.return_value.in_.return_value.execute.return_value.data = (
        _ref_rows()
    )
    with patch(
        "app.portfolio.router.get_admin_db", return_value=rest_db
    ), patch(
        "app.portfolio.router._assert_owns_account"
    ), patch(
        "app.portfolio.router.snapshots.ensure_today_snapshot"
    ), patch(
        "app.portfolio.router.snapshots.get_latest_snapshot",
        return_value=_exposure_snapshot(),
    ):
        rest_models = asyncio.run(
            get_exposure(dim="asset_class", account_id=UUID(ACCOUNT_ID),
                         user=fake_user)
        )
    rest_slices = [s.model_dump() for s in rest_models]

    # Sort both lists by label and compare field-by-field.
    mcp_sorted = sorted(mcp_slices, key=lambda s: s["label"])
    rest_sorted = sorted(rest_slices, key=lambda s: s["label"])
    assert [s["label"] for s in mcp_sorted] == [s["label"] for s in rest_sorted]
    for m, r in zip(mcp_sorted, rest_sorted):
        assert m["label"] == r["label"]
        assert m["market_value"] == pytest.approx(r["market_value"], rel=1e-6)
        assert m["percent"] == pytest.approx(r["percent"], abs=0.01)


def test_exposure_error_parity_on_invalid_dimension():
    """Both surfaces must reject an invalid dimension."""
    fake_user = MagicMock()
    fake_user.id = UUID(int=1)
    fake_db = MagicMock()

    mcp_result = portfolio_get_exposure(
        fake_db, USER_ID, dimension="bogus"
    )
    assert mcp_result == [{"error": "dimension must be one of: asset_class, sector, region"}]

    from fastapi import HTTPException

    with patch("app.portfolio.router.get_admin_db", return_value=fake_db), \
         patch("app.portfolio.router.snapshots.ensure_today_snapshot"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_exposure(dim="bogus", user=fake_user))
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# D3 — Attribution + macro context (MCP vs REST)
# ---------------------------------------------------------------------------

def _attribution_snapshots() -> list[dict]:
    return [
        {
            "id": "s1", "account_id": ACCOUNT_ID,
            "snapshot_date": "2026-04-01", "source": "manual",
            "total_value": 8_000, "cash_value": 0,
            "created_at": "2026-04-01T00:00:00Z",
            "holdings": [{"ticker": "NVDA", "quantity": 10, "price": 800,
                          "market_value": 8_000, "cost_basis": None,
                          "unrealized_gain": None}],
        },
        {
            "id": "s2", "account_id": ACCOUNT_ID,
            "snapshot_date": "2026-05-01", "source": "manual",
            "total_value": 9_000, "cash_value": 0,
            "created_at": "2026-05-01T00:00:00Z",
            "holdings": [{"ticker": "NVDA", "quantity": 10, "price": 900,
                          "market_value": 9_000, "cost_basis": None,
                          "unrealized_gain": None}],
        },
    ]


def _attribution_prices() -> dict:
    return {
        ("NVDA", date(2026, 4, 1)): 800.0,
        ("NVDA", date(2026, 5, 1)): 900.0,
        ("SPY", date(2026, 4, 1)): 500.0,
        ("SPY", date(2026, 5, 1)): 510.0,
    }


def _attribution_txns() -> list[dict]:
    return [
        {"type": "dividend", "amount": 25.0, "account_id": ACCOUNT_ID,
         "date": "2026-04-15"},
    ]


def _ten_year_series() -> dict:
    return {date(2026, 4, 1): 4.20, date(2026, 5, 1): 4.50}


def _cpi_series() -> dict:
    return {date(2026, 3, 1): 3.20, date(2026, 4, 1): 3.10}


def test_attribution_differential_mcp_vs_rest_includes_macro():
    """MCP `portfolio_get_attribution` and REST `get_attribution` agree on all
    decomp buckets AND macro context fields after the macro-alignment fix."""
    fake_user = MagicMock()
    fake_user.id = UUID(int=1)

    fd = "2026-04-01"
    td = "2026-05-01"

    # MCP path
    mcp_db = MagicMock()

    def _mcp_table(name: str) -> MagicMock:
        t = MagicMock()
        if name == "accounts":
            t.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = [
                {"id": ACCOUNT_ID}
            ]
        elif name == "investment_transactions":
            t.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value.data = (
                _attribution_txns()
            )
        return t

    mcp_db.table.side_effect = _mcp_table

    def _mcp_get_prices(_db, tickers, fd_, td_):
        wanted = set(tickers)
        return {k: v for k, v in _attribution_prices().items() if k[0] in wanted}

    with patch(
        "app.portfolio.snapshots.get_snapshots_in_window",
        return_value=_attribution_snapshots(),
    ), patch(
        "app.portfolio.reference.get_prices",
        side_effect=_mcp_get_prices,
    ), patch(
        "app.portfolio.fred.fetch_fred_series",
        side_effect=lambda series, *_a, **_k: (
            _ten_year_series() if series == "DGS10" else _cpi_series()
        ),
    ):
        mcp_result = portfolio_get_attribution(
            mcp_db, USER_ID, from_date=fd, to_date=td,
        )

    # REST path
    rest_db = MagicMock()

    def _rest_table(name: str) -> MagicMock:
        t = MagicMock()
        if name == "accounts":
            t.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = [
                {"id": ACCOUNT_ID}
            ]
        elif name == "investment_transactions":
            t.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value.data = (
                _attribution_txns()
            )
        return t

    rest_db.table.side_effect = _rest_table

    with patch(
        "app.portfolio.router.get_admin_db", return_value=rest_db
    ), patch(
        "app.portfolio.router.snapshots.get_snapshots_in_window",
        return_value=_attribution_snapshots(),
    ), patch(
        "app.portfolio.router.ref_module.get_prices",
        side_effect=_mcp_get_prices,
    ), patch(
        "app.portfolio.router.fetch_fred_series",
        side_effect=lambda series, *_a, **_k: (
            _ten_year_series() if series == "DGS10" else _cpi_series()
        ),
    ):
        rest_result = asyncio.run(
            get_attribution(
                from_date=date(2026, 4, 1), to_date=date(2026, 5, 1),
                user=fake_user,
            )
        )
    rest_dict = rest_result.model_dump()

    # Decomp buckets must match.
    for key in ("contributions", "withdrawals", "dividends", "trades",
                "market", "unattributed"):
        assert mcp_result[key] == pytest.approx(rest_dict[key], abs=1e-6), key

    # Macro context — D3 says assert EQUALITY post-alignment fix.
    mcp_macro = mcp_result["macro_context"]
    rest_macro = rest_dict["macro_context"]
    assert mcp_macro["ten_year_yield_change_bps"] == pytest.approx(
        rest_macro["ten_year_yield_change_bps"], abs=0.5
    )
    assert mcp_macro["cpi_yoy_at_end"] == pytest.approx(
        rest_macro["cpi_yoy_at_end"], rel=1e-6
    )
    assert mcp_macro["spy_period_return_pct"] == pytest.approx(
        rest_macro["spy_period_return_pct"], rel=1e-6
    )


def test_attribution_error_parity_on_inverted_window():
    """Both surfaces must reject from_date >= to_date."""
    fake_user = MagicMock()
    fake_user.id = UUID(int=1)
    fake_db = MagicMock()

    # MCP: portfolio_get_attribution doesn't validate the window itself; it
    # falls through to "no snapshots" or "no investment accounts". Document the
    # actual behavior so a future refactor that adds validation is visible.
    fake_db.table.return_value.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = []
    mcp_result = portfolio_get_attribution(
        fake_db, USER_ID, from_date="2026-05-01", to_date="2026-04-01",
    )
    assert "error" in mcp_result

    # REST: explicit 400 on inverted window.
    from fastapi import HTTPException

    with patch("app.portfolio.router.get_admin_db", return_value=fake_db):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                get_attribution(
                    from_date=date(2026, 5, 1), to_date=date(2026, 4, 1),
                    user=fake_user,
                )
            )
        assert exc.value.status_code == 400
