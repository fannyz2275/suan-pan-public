import pytest
from datetime import date
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client_with_user():
    """TestClient with auth dependency overridden to a fixed test user."""
    from app.auth.middleware import get_current_user

    fake_user = MagicMock()
    fake_user.id = uuid4()
    app.dependency_overrides[get_current_user] = lambda: fake_user
    yield TestClient(app), fake_user
    app.dependency_overrides.clear()


def test_create_manual_snapshot_endpoint(client_with_user):
    client, user = client_with_user
    account_uuid = "11111111-1111-1111-1111-111111111111"
    inserted = {
        "id": str(uuid4()), "user_id": str(user.id),
        "account_id": account_uuid, "snapshot_date": "2026-05-06",
        "source": "manual", "total_value": 1800.0, "cash_value": 0.0,
        "created_at": "2026-05-06T00:00:00Z",
    }
    inserted_holding = {
        "snapshot_id": inserted["id"], "ticker": "NVDA", "quantity": 2.0,
        "price": 900.0, "market_value": 1800.0, "cost_basis": 1500, "unrealized_gain": 300.0,
    }

    def _make_db():
        fake_db = MagicMock()

        def _table(name):
            t = MagicMock()
            if name == "accounts":
                # _assert_owns_account query
                t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
                    {"id": account_uuid}
                ]
            elif name == "portfolio_snapshots":
                t.insert.return_value.execute.return_value.data = [inserted]
                t.update.return_value.eq.return_value.eq.return_value.eq.return_value.neq.return_value.is_.return_value.execute.return_value.data = []
            elif name == "snapshot_holdings":
                t.insert.return_value.execute.return_value.data = [inserted_holding]
            return t

        fake_db.table.side_effect = _table
        return fake_db

    with patch("app.portfolio.router.get_admin_db", side_effect=_make_db):
        resp = client.post(
            "/portfolio/snapshot/manual",
            json={
                "account_id": "11111111-1111-1111-1111-111111111111",
                "snapshot_date": "2026-05-06",
                "cash_value": 0,
                "holdings": [
                    {"ticker": "NVDA", "quantity": 2, "price": 900, "cost_basis": 1500},
                ],
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "manual"
    assert body["total_value"] == 1800.0
    # Holdings should be returned in the response (Fix 4).
    assert len(body["holdings"]) == 1
    assert body["holdings"][0]["ticker"] == "NVDA"


def test_get_holdings_returns_latest_snapshot_holdings(client_with_user):
    client, user = client_with_user
    account_uuid = "11111111-1111-1111-1111-111111111111"
    snapshot = {
        "id": "snap-1", "account_id": "acc-1",
        "snapshot_date": "2026-05-01", "source": "manual",
        "total_value": 10000, "cash_value": 0,
        "created_at": "2026-05-01T00:00:00Z",
    }

    def _make_db():
        fake_db = MagicMock()

        def _table(name):
            t = MagicMock()
            if name == "accounts":
                # _assert_owns_account: .select().eq().eq().limit().execute()
                t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
                    {"id": account_uuid}
                ]
            elif name == "portfolio_snapshots":
                t.select.return_value.eq.return_value.is_.return_value.order.return_value.limit.return_value.execute.return_value.data = [snapshot]
            elif name == "snapshot_holdings":
                t.select.return_value.eq.return_value.execute.return_value.data = [
                    {"snapshot_id": "snap-1", "ticker": "NVDA", "quantity": 10,
                     "price": 900, "market_value": 9000, "cost_basis": 7000, "unrealized_gain": 2000},
                    {"snapshot_id": "snap-1", "ticker": "AAPL", "quantity": 5,
                     "price": 200, "market_value": 1000, "cost_basis": 800, "unrealized_gain": 200},
                ]
            return t

        fake_db.table.side_effect = _table
        return fake_db

    with patch("app.portfolio.router.get_admin_db", side_effect=_make_db):
        resp = client.get(f"/portfolio/holdings?account_id={account_uuid}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Sort for stable golden ordering across percent ties.
    body_sorted = sorted(body, key=lambda h: h["ticker"])
    assert body_sorted == _GOLDEN_HOLDINGS_RESPONSE


_GOLDEN_HOLDINGS_RESPONSE = [
    {"ticker": "AAPL", "name": None, "quantity": 5.0, "price": 200.0,
     "market_value": 1000.0, "percent": 10.0,
     "cost_basis": 800.0, "unrealized_gain": 200.0},
    {"ticker": "NVDA", "name": None, "quantity": 10.0, "price": 900.0,
     "market_value": 9000.0, "percent": 90.0,
     "cost_basis": 7000.0, "unrealized_gain": 2000.0},
]


def test_get_exposure(client_with_user):
    client, user = client_with_user
    account_uuid = "11111111-1111-1111-1111-111111111111"
    snapshot = {
        "id": "snap-1", "account_id": "acc-1",
        "snapshot_date": "2026-05-01", "source": "manual",
        "total_value": 10000, "cash_value": 0,
        "created_at": "2026-05-01T00:00:00Z",
    }

    def _make_db():
        fake_db = MagicMock()

        def _table(name):
            t = MagicMock()
            if name == "accounts":
                # _assert_owns_account: .select().eq().eq().limit().execute()
                t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
                    {"id": account_uuid}
                ]
            elif name == "portfolio_snapshots":
                t.select.return_value.eq.return_value.is_.return_value.order.return_value.limit.return_value.execute.return_value.data = [snapshot]
            elif name == "snapshot_holdings":
                t.select.return_value.eq.return_value.execute.return_value.data = [
                    {"snapshot_id": "snap-1", "ticker": "NVDA", "quantity": 10,
                     "price": 900, "market_value": 9000, "cost_basis": None, "unrealized_gain": None},
                    {"snapshot_id": "snap-1", "ticker": "BND", "quantity": 5,
                     "price": 200, "market_value": 1000, "cost_basis": None, "unrealized_gain": None},
                ]
            elif name == "security_reference":
                t.select.return_value.in_.return_value.execute.return_value.data = [
                    {"ticker": "NVDA", "asset_class": "equity", "sector": "Technology",
                     "region": "US", "look_through": None},
                    {"ticker": "BND", "asset_class": "fixed_income", "sector": None,
                     "region": "US", "look_through": None},
                ]
            return t

        fake_db.table.side_effect = _table
        return fake_db

    with patch("app.portfolio.router.get_admin_db", side_effect=_make_db):
        resp = client.get(
            f"/portfolio/exposure?account_id={account_uuid}&dim=asset_class"
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_label = {s["label"]: s for s in body}
    assert by_label["equity"]["market_value"] == 9000
    assert by_label["fixed_income"]["market_value"] == 1000


def test_get_timeseries(client_with_user):
    client, user = client_with_user
    fake_db = MagicMock()
    # accounts query returns one account
    fake_db.table.return_value.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = [
        {"id": "acc-1"}
    ]
    # snapshots-in-window
    fake_db.table.return_value.select.return_value.in_.return_value.is_.return_value.lte.return_value.order.return_value.execute.return_value.data = [
        {"id": "snap-1", "account_id": "acc-1", "snapshot_date": "2026-04-01",
         "source": "manual", "total_value": 9000, "cash_value": 0,
         "created_at": "2026-04-01T00:00:00Z"},
    ]
    # holdings for those snapshots
    fake_db.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
        {"snapshot_id": "snap-1", "ticker": "NVDA", "quantity": 10,
         "price": 900, "market_value": 9000, "cost_basis": None, "unrealized_gain": None},
    ]
    # security_prices
    fake_db.table.return_value.select.return_value.in_.return_value.gte.return_value.lte.return_value.execute.return_value.data = [
        {"ticker": "NVDA", "date": "2026-04-01", "close": 900},
        {"ticker": "NVDA", "date": "2026-04-02", "close": 920},
    ]
    with patch("app.portfolio.router.get_admin_db", return_value=fake_db):
        resp = client.get("/portfolio/timeseries?from_date=2026-04-01&to_date=2026-04-02")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "series" in body
    assert len(body["series"]) == 2
    assert body["series"][0]["total_value"] == 9000.0
    assert body["series"][1]["total_value"] == 9200.0


def test_statement_preview_text_endpoint(client_with_user, snapshot_json):
    client, user = client_with_user

    fake_parsed = {
        "statement_date": "2026-04-30",
        "cash_value": 100.0,
        "account_hint": "Fidelity ...1234",
        "holdings": [{
            "ticker": "NVDA", "name": "NVIDIA", "quantity": 5,
            "price": 950, "market_value": 4750, "cost_basis": 4000,
        }],
        "investment_transactions": [{
            "date": "2026-04-15", "type": "buy", "ticker": "NVDA",
            "quantity": 2, "price": 920, "amount": -1840,
        }],
    }
    with patch("app.portfolio.router.parse_investment_statement", return_value=fake_parsed):
        resp = client.post(
            "/portfolio/import/statement",
            json={"text": "fake statement text"},
        )
    assert resp.status_code == 200, resp.text
    # Golden locks the full StatementPreview shape — schema changes (new fields,
    # renames, type drift) become a single visible diff on the snapshot file.
    assert resp.json() == snapshot_json


def test_statement_preview_file_endpoint_pdf(client_with_user):
    client, user = client_with_user

    fake_parsed = {
        "statement_date": "2026-04-30", "cash_value": 0,
        "account_hint": None,
        "holdings": [],
        "investment_transactions": [],
    }
    with patch("app.portfolio.router.extract_pdf_text", return_value="extracted text"):
        with patch("app.portfolio.router.parse_investment_statement", return_value=fake_parsed):
            resp = client.post(
                "/portfolio/import/statement/file",
                files={"file": ("statement.pdf", b"%PDF-1.4 fake bytes", "application/pdf")},
            )
    assert resp.status_code == 200, resp.text
    assert resp.json()["holdings"] == []


def test_statement_preview_file_rejects_unknown_extension(client_with_user):
    client, _ = client_with_user
    resp = client.post(
        "/portfolio/import/statement/file",
        files={"file": ("statement.xlsx", b"fake", "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_statement_import_confirm_endpoint(client_with_user):
    client, user = client_with_user
    account_uuid = "11111111-1111-1111-1111-111111111111"
    snap_uuid = "22222222-2222-2222-2222-222222222222"
    fake_db = MagicMock()
    inserted_snap = {
        "id": snap_uuid, "user_id": str(user.id),
        "account_id": account_uuid,
        "snapshot_date": "2026-04-30", "source": "statement_import",
        "total_value": 9500.0, "cash_value": 0.0,
        "created_at": "2026-04-30T00:00:00Z",
    }
    inserted_holdings = [
        {"id": "h1", "snapshot_id": snap_uuid, "ticker": "NVDA",
         "quantity": 10, "price": 950, "market_value": 9500,
         "cost_basis": 7000, "unrealized_gain": 2500},
    ]

    def table(name):
        t = MagicMock()
        if name == "accounts":
            t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": account_uuid, "type": "brokerage"}]
        elif name == "portfolio_snapshots":
            t.insert.return_value.execute.return_value.data = [inserted_snap]
            t.update.return_value.eq.return_value.eq.return_value.eq.return_value.neq.return_value.is_.return_value.execute.return_value.data = []
        elif name == "snapshot_holdings":
            t.insert.return_value.execute.return_value.data = inserted_holdings
        elif name == "investment_transactions":
            t.insert.return_value.execute.return_value.data = [{"id": "t1"}]
        return t
    fake_db.table.side_effect = table

    with patch("app.portfolio.router.get_admin_db", return_value=fake_db):
        resp = client.post(
            "/portfolio/import/statement/confirm",
            json={
                "account_id": account_uuid,
                "statement_date": "2026-04-30",
                "cash_value": 0,
                "holdings": [{
                    "ticker": "NVDA", "name": "NVIDIA",
                    "quantity": 10, "price": 950, "market_value": 9500,
                    "cost_basis": 7000,
                }],
                "investment_transactions": [{
                    "date": "2026-04-15", "type": "buy", "ticker": "NVDA",
                    "quantity": 2, "price": 920, "amount": -1840,
                }],
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "statement_import"
    assert body["total_value"] == 9500.0
    assert len(body["holdings"]) == 1


def test_statement_import_confirm_rejects_other_users_account(client_with_user):
    client, _ = client_with_user
    fake_db = MagicMock()
    # Account ownership check returns no rows.
    def table(name):
        t = MagicMock()
        if name == "accounts":
            t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        return t
    fake_db.table.side_effect = table

    with patch("app.portfolio.router.get_admin_db", return_value=fake_db):
        resp = client.post(
            "/portfolio/import/statement/confirm",
            json={
                "account_id": "99999999-9999-9999-9999-999999999999",
                "statement_date": "2026-04-30",
                "cash_value": 0,
                "holdings": [],
                "investment_transactions": [],
            },
        )
    assert resp.status_code == 404


def test_statement_preview_round_trips_total_value_reported(client_with_user):
    client, _ = client_with_user
    fake_parsed = {
        "statement_date": "2026-04-30",
        "cash_value": 100.0,
        "account_hint": None,
        "total_value_reported": 19999.99,
        "holdings": [],
        "investment_transactions": [],
    }
    with patch("app.portfolio.router.parse_investment_statement", return_value=fake_parsed):
        resp = client.post("/portfolio/import/statement", json={"text": "stmt"})
    assert resp.status_code == 200
    assert resp.json()["total_value_reported"] == 19999.99


def test_statement_import_confirm_rejects_non_investment_account(client_with_user):
    client, _ = client_with_user
    account_uuid = "33333333-3333-3333-3333-333333333333"
    fake_db = MagicMock()
    def table(name):
        t = MagicMock()
        if name == "accounts":
            t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
                {"id": account_uuid, "type": "checking"},
            ]
        return t
    fake_db.table.side_effect = table

    with patch("app.portfolio.router.get_admin_db", return_value=fake_db):
        resp = client.post(
            "/portfolio/import/statement/confirm",
            json={
                "account_id": account_uuid, "statement_date": "2026-04-30",
                "cash_value": 0, "holdings": [], "investment_transactions": [],
            },
        )
    assert resp.status_code == 400


def test_get_attribution_endpoint(client_with_user):
    client, user = client_with_user
    account_uuid = "11111111-1111-1111-1111-111111111111"
    fake_db = MagicMock()

    # Two snapshots: start ($10k) and end ($11k), no txns in window.
    snapshots = [
        {"id": "s-start", "account_id": account_uuid, "snapshot_date": "2026-03-01",
         "source": "manual", "total_value": 10_000, "cash_value": 0,
         "created_at": "2026-03-01T00:00:00Z"},
        {"id": "s-end", "account_id": account_uuid, "snapshot_date": "2026-04-01",
         "source": "manual", "total_value": 11_000, "cash_value": 0,
         "created_at": "2026-04-01T00:00:00Z"},
    ]
    holdings = [
        {"snapshot_id": "s-start", "ticker": "NVDA", "quantity": 10,
         "price": 1000, "market_value": 10_000, "cost_basis": None, "unrealized_gain": None},
        {"snapshot_id": "s-end", "ticker": "NVDA", "quantity": 10,
         "price": 1100, "market_value": 11_000, "cost_basis": None, "unrealized_gain": None},
    ]

    def table(name):
        t = MagicMock()
        if name == "accounts":
            t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": account_uuid}]
        elif name == "portfolio_snapshots":
            t.select.return_value.in_.return_value.is_.return_value.lte.return_value.order.return_value.execute.return_value.data = snapshots
        elif name == "snapshot_holdings":
            t.select.return_value.in_.return_value.execute.return_value.data = holdings
        elif name == "investment_transactions":
            t.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value.data = []
        elif name == "security_prices":
            t.select.return_value.in_.return_value.gte.return_value.lte.return_value.execute.return_value.data = [
                {"ticker": "NVDA", "date": "2026-03-01", "close": 1000},
                {"ticker": "NVDA", "date": "2026-04-01", "close": 1100},
            ]
        return t
    fake_db.table.side_effect = table

    with patch("app.portfolio.router.get_admin_db", return_value=fake_db):
        with patch("app.portfolio.router.fetch_fred_series", return_value={}):
            resp = client.get(
                f"/portfolio/attribution?from_date=2026-03-01&to_date=2026-04-01&account_id={account_uuid}"
            )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["start_value"] == 10_000
    assert body["end_value"] == 11_000
    assert body["market"] == 1_000
    assert body["contributions"] == 0
    assert body["unattributed"] == 0


def test_get_attribution_rejects_inverted_window(client_with_user):
    client, _ = client_with_user
    resp = client.get("/portfolio/attribution?from_date=2026-04-01&to_date=2026-03-01")
    assert resp.status_code == 400


def test_get_timeseries_with_macro_overlay(client_with_user):
    client, user = client_with_user
    fake_db = MagicMock()
    # Reuse the existing get_timeseries setup pattern:
    fake_db.table.return_value.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = [{"id": "acc-1"}]
    fake_db.table.return_value.select.return_value.in_.return_value.is_.return_value.lte.return_value.order.return_value.execute.return_value.data = [
        {"id": "snap-1", "account_id": "acc-1", "snapshot_date": "2026-04-01",
         "source": "manual", "total_value": 9000, "cash_value": 0,
         "created_at": "2026-04-01T00:00:00Z"},
    ]
    fake_db.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
        {"snapshot_id": "snap-1", "ticker": "NVDA", "quantity": 10,
         "price": 900, "market_value": 9000, "cost_basis": None, "unrealized_gain": None},
    ]
    fake_db.table.return_value.select.return_value.in_.return_value.gte.return_value.lte.return_value.execute.return_value.data = [
        {"ticker": "NVDA", "date": "2026-04-01", "close": 900},
        {"ticker": "NVDA", "date": "2026-04-02", "close": 920},
    ]

    fred_responses = {
        "DGS10": {date(2026, 4, 1): 4.20, date(2026, 4, 2): 4.18},
        "CPIAUCSL": {date(2026, 4, 1): 3.1, date(2026, 4, 2): 3.1},
    }
    def fred_side(series_id, *_args, **_kwargs):
        return fred_responses.get(series_id, {})

    with patch("app.portfolio.router.get_admin_db", return_value=fake_db):
        with patch("app.portfolio.router.fetch_fred_series", side_effect=fred_side):
            resp = client.get(
                "/portfolio/timeseries?from_date=2026-04-01&to_date=2026-04-02&overlays=10y,cpi"
            )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # New shape: { "series": [...portfolio points...], "overlays": [...macro points...] }
    assert "series" in body
    assert "overlays" in body
    assert len(body["series"]) == 2
    overlay_by_date = {p["date"]: p for p in body["overlays"]}
    assert overlay_by_date["2026-04-01"]["ten_year_yield"] == 4.20
    assert overlay_by_date["2026-04-02"]["cpi_yoy"] == 3.1


def test_post_sync_plaid_calls_sync_and_returns_count(client_with_user):
    client, user = client_with_user
    fake_db = MagicMock()
    fake_snaps = [{"id": "s1"}, {"id": "s2"}]
    with patch("app.portfolio.router.get_admin_db", return_value=fake_db):
        with patch("app.portfolio.router.sync_plaid_investments", return_value=fake_snaps) as mock_sync:
            with patch("app.portfolio.router._build_plaid_client") as mock_build:
                resp = client.post("/portfolio/sync/plaid")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["snapshots_written"] == 2
    mock_sync.assert_called_once()
