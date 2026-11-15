"""Spec B Phase 3 — REST endpoint tests for /portfolio/* (§4c).

Each test:
  1. Overrides `get_current_user` to a fixed fake user.
  2. Patches `get_admin_db` to a MagicMock wired to fixture data.
  3. Calls the endpoint via TestClient.
  4. Round-trips the response through the matching Pydantic schema (§9).
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.middleware import get_current_user
from app.main import app
from app.portfolio import schemas


_ACCOUNT_UUID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client_with_user():
    """TestClient with auth dependency overridden to a fixed user."""
    fake_user = MagicMock()
    fake_user.id = UUID(int=1)
    app.dependency_overrides[get_current_user] = lambda: fake_user
    yield TestClient(app), fake_user
    app.dependency_overrides.clear()


def _stub_owns(name: str) -> MagicMock:
    """Return a MagicMock table that satisfies _assert_owns_account."""
    t = MagicMock()
    t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": _ACCOUNT_UUID, "type": "brokerage"}
    ]
    return t


# ---------------------------------------------------------------------------
# POST /portfolio/snapshot/manual
# ---------------------------------------------------------------------------

def test_post_manual_snapshot_round_trips_schema(client_with_user):
    client, _ = client_with_user
    inserted = {
        "id": str(uuid4()),
        "account_id": _ACCOUNT_UUID,
        "snapshot_date": "2026-05-06",
        "source": "manual",
        "total_value": 1_800.0,
        "cash_value": 0.0,
        "created_at": "2026-05-06T00:00:00Z",
        "holdings": [
            {
                "ticker": "NVDA",
                "quantity": 2.0,
                "price": 900.0,
                "market_value": 1_800.0,
                "cost_basis": 1_500.0,
                "unrealized_gain": 300.0,
            }
        ],
    }

    db = MagicMock()
    db.table.side_effect = lambda name: _stub_owns(name) if name == "accounts" else MagicMock()

    with patch("app.portfolio.router.get_admin_db", return_value=db), \
         patch(
             "app.portfolio.router.snapshots.create_manual_snapshot",
             return_value=inserted,
         ):
        resp = client.post(
            "/portfolio/snapshot/manual",
            json={
                "account_id": _ACCOUNT_UUID,
                "snapshot_date": "2026-05-06",
                "cash_value": 0,
                "holdings": [
                    {"ticker": "NVDA", "quantity": 2, "price": 900, "cost_basis": 1500},
                ],
            },
        )

    assert resp.status_code == 200, resp.text
    parsed = schemas.SnapshotOut.model_validate(resp.json())
    assert parsed.source == "manual"
    assert parsed.total_value == 1_800.0
    assert len(parsed.holdings) == 1
    assert parsed.holdings[0].ticker == "NVDA"


# ---------------------------------------------------------------------------
# GET /portfolio/holdings
# ---------------------------------------------------------------------------

def test_get_holdings_round_trips_schema(client_with_user):
    client, _ = client_with_user
    snapshot = {
        "id": "snap-1",
        "account_id": "acc-1",
        "snapshot_date": "2026-05-01",
        "source": "manual",
        "total_value": 10_000,
        "cash_value": 0,
        "created_at": "2026-05-01T00:00:00Z",
        "holdings": [
            {"ticker": "NVDA", "quantity": 10, "price": 900, "market_value": 9_000,
             "cost_basis": 7_000, "unrealized_gain": 2_000},
            {"ticker": "AAPL", "quantity": 5, "price": 200, "market_value": 1_000,
             "cost_basis": 800, "unrealized_gain": 200},
        ],
    }

    db = MagicMock()
    db.table.side_effect = lambda name: _stub_owns(name) if name == "accounts" else MagicMock()

    with patch("app.portfolio.router.get_admin_db", return_value=db), \
         patch("app.portfolio.router.snapshots.ensure_today_snapshot"), \
         patch(
             "app.portfolio.router.snapshots.get_latest_snapshot",
             return_value=snapshot,
         ):
        resp = client.get(f"/portfolio/holdings?account_id={_ACCOUNT_UUID}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 2
    for h in body:
        schemas.HoldingOut.model_validate(h)
    nvda = next(h for h in body if h["ticker"] == "NVDA")
    assert abs(nvda["percent"] - 90.0) < 0.01


def test_get_holdings_returns_empty_list_when_no_snapshot(client_with_user):
    client, _ = client_with_user
    db = MagicMock()
    db.table.side_effect = lambda name: _stub_owns(name) if name == "accounts" else MagicMock()

    with patch("app.portfolio.router.get_admin_db", return_value=db), \
         patch("app.portfolio.router.snapshots.ensure_today_snapshot"), \
         patch(
             "app.portfolio.router.snapshots.get_latest_snapshot",
             return_value=None,
         ):
        resp = client.get(f"/portfolio/holdings?account_id={_ACCOUNT_UUID}")

    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /portfolio/exposure
# ---------------------------------------------------------------------------

def test_get_exposure_round_trips_schema(client_with_user):
    client, _ = client_with_user
    snapshot = {
        "id": "snap-1",
        "account_id": "acc-1",
        "snapshot_date": "2026-05-01",
        "source": "manual",
        "total_value": 10_000,
        "cash_value": 0,
        "created_at": "2026-05-01T00:00:00Z",
        "holdings": [
            {"ticker": "NVDA", "quantity": 10, "price": 900, "market_value": 9_000,
             "cost_basis": None, "unrealized_gain": None},
            {"ticker": "BND", "quantity": 5, "price": 200, "market_value": 1_000,
             "cost_basis": None, "unrealized_gain": None},
        ],
    }

    def _table(name: str) -> MagicMock:
        t = MagicMock()
        if name == "accounts":
            return _stub_owns(name)
        if name == "security_reference":
            t.select.return_value.in_.return_value.execute.return_value.data = [
                {"ticker": "NVDA", "asset_class": "equity", "sector": "Technology",
                 "region": "US", "look_through": None},
                {"ticker": "BND", "asset_class": "fixed_income", "sector": None,
                 "region": "US", "look_through": None},
            ]
        return t

    db = MagicMock()
    db.table.side_effect = _table

    with patch("app.portfolio.router.get_admin_db", return_value=db), \
         patch("app.portfolio.router.snapshots.ensure_today_snapshot"), \
         patch(
             "app.portfolio.router.snapshots.get_latest_snapshot",
             return_value=snapshot,
         ):
        resp = client.get(
            f"/portfolio/exposure?account_id={_ACCOUNT_UUID}&dim=asset_class"
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    for slice_ in body:
        schemas.ExposureSlice.model_validate(slice_)
    by_label = {s["label"]: s for s in body}
    assert by_label["equity"]["market_value"] == 9_000
    assert by_label["fixed_income"]["market_value"] == 1_000


def test_get_exposure_rejects_invalid_dimension(client_with_user):
    client, _ = client_with_user
    resp = client.get(f"/portfolio/exposure?account_id={_ACCOUNT_UUID}&dim=bogus")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /portfolio/timeseries
# ---------------------------------------------------------------------------

def test_get_timeseries_round_trips_schema(client_with_user):
    client, _ = client_with_user

    def _table(name: str) -> MagicMock:
        t = MagicMock()
        if name == "accounts":
            t.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = [
                {"id": _ACCOUNT_UUID}
            ]
        return t

    db = MagicMock()
    db.table.side_effect = _table

    snaps = [
        {
            "id": "s1",
            "account_id": _ACCOUNT_UUID,
            "snapshot_date": "2026-05-01",
            "source": "manual",
            "total_value": 8_000,
            "cash_value": 0,
            "created_at": "2026-05-01T00:00:00Z",
            "holdings": [{"ticker": "NVDA", "quantity": 10, "price": 800,
                           "market_value": 8_000, "cost_basis": None, "unrealized_gain": None}],
        },
    ]

    with patch("app.portfolio.router.get_admin_db", return_value=db), \
         patch("app.portfolio.router.snapshots.ensure_today_snapshot"), \
         patch(
             "app.portfolio.router.snapshots.get_snapshots_in_window",
             return_value=snaps,
         ), \
         patch(
             "app.portfolio.router.ref_module.get_prices",
             return_value={("NVDA", date(2026, 5, 1)): 800.0,
                           ("NVDA", date(2026, 5, 2)): 810.0},
         ):
        resp = client.get("/portfolio/timeseries?from_date=2026-05-01&to_date=2026-05-02")

    assert resp.status_code == 200, resp.text
    parsed = schemas.TimeSeriesResponse.model_validate(resp.json())
    assert len(parsed.series) == 2


def test_get_timeseries_rejects_inverted_window(client_with_user):
    client, _ = client_with_user
    resp = client.get("/portfolio/timeseries?from_date=2026-05-10&to_date=2026-05-01")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /portfolio/attribution
# ---------------------------------------------------------------------------

def test_get_attribution_round_trips_schema(client_with_user):
    client, _ = client_with_user

    snaps = [
        {
            "id": "s1",
            "account_id": _ACCOUNT_UUID,
            "snapshot_date": "2026-04-01",
            "source": "manual",
            "total_value": 8_000,
            "cash_value": 0,
            "created_at": "2026-04-01T00:00:00Z",
            "holdings": [{"ticker": "NVDA", "quantity": 10, "price": 800,
                          "market_value": 8_000, "cost_basis": None, "unrealized_gain": None}],
        },
        {
            "id": "s2",
            "account_id": _ACCOUNT_UUID,
            "snapshot_date": "2026-05-01",
            "source": "manual",
            "total_value": 9_000,
            "cash_value": 0,
            "created_at": "2026-05-01T00:00:00Z",
            "holdings": [{"ticker": "NVDA", "quantity": 10, "price": 900,
                          "market_value": 9_000, "cost_basis": None, "unrealized_gain": None}],
        },
    ]

    def _table(name: str) -> MagicMock:
        t = MagicMock()
        if name == "accounts":
            t.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = [
                {"id": _ACCOUNT_UUID}
            ]
        elif name == "investment_transactions":
            t.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value.data = [
                {"type": "dividend", "amount": 25.0, "account_id": _ACCOUNT_UUID},
            ]
        return t

    db = MagicMock()
    db.table.side_effect = _table

    with patch("app.portfolio.router.get_admin_db", return_value=db), \
         patch(
             "app.portfolio.router.snapshots.get_snapshots_in_window",
             return_value=snaps,
         ), \
         patch(
             "app.portfolio.router.ref_module.get_prices",
             return_value={
                 ("NVDA", date(2026, 4, 1)): 800.0,
                 ("NVDA", date(2026, 5, 1)): 900.0,
             },
         ), \
         patch("app.portfolio.router.fetch_fred_series", return_value={}):
        resp = client.get(
            "/portfolio/attribution?from_date=2026-04-01&to_date=2026-05-01"
        )

    assert resp.status_code == 200, resp.text
    parsed = schemas.AttributionResult.model_validate(resp.json())
    assert parsed.dividends == 25.0
    assert parsed.macro_context is not None


def test_get_attribution_rejects_inverted_window(client_with_user):
    client, _ = client_with_user
    resp = client.get(
        "/portfolio/attribution?from_date=2026-05-01&to_date=2026-04-01"
    )
    assert resp.status_code == 400


def test_get_attribution_no_accounts_returns_zero_response(client_with_user):
    client, _ = client_with_user
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = []

    with patch("app.portfolio.router.get_admin_db", return_value=db):
        resp = client.get(
            "/portfolio/attribution?from_date=2026-04-01&to_date=2026-05-01"
        )

    assert resp.status_code == 200
    parsed = schemas.AttributionResult.model_validate(resp.json())
    assert parsed.start_value == 0
    assert parsed.end_value == 0


# ---------------------------------------------------------------------------
# POST /portfolio/import/statement (Gemini mocked)
# ---------------------------------------------------------------------------

def _fake_gemini_client(text: str) -> MagicMock:
    client = MagicMock()
    client.models.generate_content.return_value.text = text
    return client


def test_post_import_statement_text_round_trips_schema(client_with_user):
    client, _ = client_with_user
    fake_response = """
    {
      "statement_date": "2026-04-30",
      "cash_value": 1234.56,
      "account_hint": "Fidelity ...1234",
      "total_value_reported": 11234.56,
      "holdings": [
        {"ticker": "NVDA", "name": "NVIDIA", "quantity": 10, "price": 1000, "market_value": 10000, "cost_basis": 7000}
      ],
      "investment_transactions": []
    }
    """
    with patch(
        "app.portfolio.statement_parser.gemini_client",
        return_value=_fake_gemini_client(fake_response),
    ):
        resp = client.post(
            "/portfolio/import/statement",
            json={"text": "ignored raw statement text"},
        )

    assert resp.status_code == 200, resp.text
    parsed = schemas.StatementPreview.model_validate(resp.json())
    assert parsed.cash_value == 1234.56
    assert parsed.total_value_reported == 11234.56
    assert len(parsed.holdings) == 1
    assert parsed.holdings[0].ticker == "NVDA"


def test_post_import_statement_text_rejects_empty_body(client_with_user):
    client, _ = client_with_user
    resp = client.post("/portfolio/import/statement", json={"text": "  "})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /portfolio/import/statement/confirm
# ---------------------------------------------------------------------------

def test_post_import_statement_confirm_round_trips_schema(client_with_user):
    client, _ = client_with_user
    inserted = {
        "id": str(uuid4()),
        "account_id": _ACCOUNT_UUID,
        "snapshot_date": "2026-04-30",
        "source": "statement_import",
        "total_value": 10_000.0,
        "cash_value": 0.0,
        "created_at": "2026-04-30T00:00:00Z",
        "holdings": [{
            "ticker": "NVDA", "quantity": 10, "price": 1000.0, "market_value": 10000.0,
            "cost_basis": 7000.0, "unrealized_gain": 3000.0,
        }],
    }

    db = MagicMock()
    db.table.side_effect = lambda name: _stub_owns(name) if name == "accounts" else MagicMock()

    with patch("app.portfolio.router.get_admin_db", return_value=db), \
         patch(
             "app.portfolio.router.snapshots.create_statement_snapshot",
             return_value=inserted,
         ):
        resp = client.post(
            "/portfolio/import/statement/confirm",
            json={
                "account_id": _ACCOUNT_UUID,
                "statement_date": "2026-04-30",
                "cash_value": 0,
                "holdings": [
                    {"ticker": "NVDA", "quantity": 10, "price": 1000,
                     "market_value": 10000, "cost_basis": 7000},
                ],
                "investment_transactions": [],
            },
        )

    assert resp.status_code == 200, resp.text
    parsed = schemas.SnapshotOut.model_validate(resp.json())
    assert parsed.source == "statement_import"
    assert parsed.total_value == 10_000.0


# ---------------------------------------------------------------------------
# GET /portfolio/summary
# ---------------------------------------------------------------------------

def test_get_summary_round_trips_schema(client_with_user):
    """Summary stitches get_timeseries + get_holdings; we patch the underlying
    DB calls and verify the response shape passes Pydantic validation."""
    client, _ = client_with_user

    snap = {
        "id": "s1",
        "account_id": _ACCOUNT_UUID,
        "snapshot_date": "2026-04-15",
        "source": "manual",
        "total_value": 9_000,
        "cash_value": 0,
        "created_at": "2026-04-15T00:00:00Z",
        "holdings": [
            {"ticker": "NVDA", "quantity": 10, "price": 900,
             "market_value": 9_000, "cost_basis": None, "unrealized_gain": None},
        ],
    }

    def _table(name: str) -> MagicMock:
        t = MagicMock()
        if name == "accounts":
            t.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = [
                {"id": _ACCOUNT_UUID}
            ]
        return t

    db = MagicMock()
    db.table.side_effect = _table

    with patch("app.portfolio.router.get_admin_db", return_value=db), \
         patch("app.portfolio.router.snapshots.ensure_today_snapshot"), \
         patch(
             "app.portfolio.router.snapshots.get_snapshots_in_window",
             return_value=[snap],
         ), \
         patch(
             "app.portfolio.router.snapshots.get_latest_snapshot",
             return_value=snap,
         ), \
         patch(
             "app.portfolio.router.ref_module.get_prices",
             return_value={},
         ):
        resp = client.get("/portfolio/summary?window=3M")

    assert resp.status_code == 200, resp.text
    parsed = schemas.PortfolioSummary.model_validate(resp.json())
    assert parsed.total_value >= 0
    assert isinstance(parsed.top_holdings, list)
