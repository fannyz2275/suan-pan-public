"""Tests the `exclude_transfers` query param on GET /finance/transactions.

Uses a stubbed Supabase client to avoid live DB calls.
"""
from datetime import datetime

from fastapi.testclient import TestClient


class _Query:
    def __init__(self, rows):
        self._rows = list(rows)
        self._filters = []
        self._not_in = []
        self._exclude_statuses: set[str] = set()
        self._keep_null_status = False

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    @property
    def not_(self):
        return _NotProxy(self)

    def or_(self, expr: str):
        # Only the router's transfer-exclude expression is expected here:
        #   transfer_status.is.null,and(transfer_status.neq.X,...)
        # Parse out the neq values and flag null-keeping.
        if "transfer_status.is.null" in expr:
            self._keep_null_status = True
        import re
        for match in re.finditer(r"transfer_status\.neq\.([a-z_]+)", expr):
            self._exclude_statuses.add(match.group(1))
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        matched = self._apply()
        start, end = getattr(self, "_range", (0, len(matched) - 1))
        return _Result(matched[start : end + 1])


class _NotProxy:
    def __init__(self, parent):
        self._parent = parent

    def in_(self, col, vals):
        self._parent._not_in.append((col, list(vals)))
        return self._parent


class _Result:
    def __init__(self, data):
        self.data = data


def _apply_filters(rows, filters, not_in, exclude_statuses, keep_null_status):
    out = []
    for r in rows:
        if not all(r.get(c) == v for (_op, c, v) in filters):
            continue
        if not all(r.get(c) not in vals for (c, vals) in not_in):
            continue
        if exclude_statuses:
            status = r.get("transfer_status")
            if status is None:
                if not keep_null_status:
                    continue
            elif status in exclude_statuses:
                continue
        out.append(r)
    return out


# Attach _apply to _Query so closures work.
_Query._apply = lambda self: _apply_filters(
    self._rows, self._filters, self._not_in,
    self._exclude_statuses, self._keep_null_status,
)


class _Client:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return _Query(self.rows)


def _base_row(**kw):
    base = {
        "id": "x",
        "user_id": "u1",
        "account_id": "a1",
        "date": "2026-04-10",
        "description": "TXN",
        "amount": -10.0,
        "category": "misc",
        "source": "manual",
        "created_at": datetime(2026, 4, 10, 12, 0, 0).isoformat(),
        "transfer_group_id": None,
        "transfer_status": None,
    }
    base.update(kw)
    return base


def _override_auth(app):
    from app.auth.middleware import get_current_user

    class _User:
        id = "u1"
        email = "u@test"

    app.dependency_overrides[get_current_user] = lambda: _User()


def test_exclude_transfers_default_hides_paired(monkeypatch):
    rows = [
        _base_row(id="1", transfer_status="auto_paired", description="TRANSFER"),
        _base_row(id="2", transfer_status=None, description="COFFEE"),
        _base_row(id="3", transfer_status="user_confirmed_internal", description="TRANSFER"),
        _base_row(id="4", transfer_status="needs_review", description="ACH"),
        _base_row(id="5", transfer_status="external", description="ACH"),
    ]
    from app.finance import router as finance_router

    monkeypatch.setattr(finance_router, "_db", lambda: _Client(rows))
    from app.main import app

    _override_auth(app)
    try:
        client = TestClient(app)
        r = client.get("/finance/transactions")
        assert r.status_code == 200
        ids = {t["id"] for t in r.json()}
        # auto_paired, user_confirmed_internal, and external hidden; the rest visible.
        assert ids == {"2", "4"}
    finally:
        app.dependency_overrides.clear()


def test_exclude_transfers_false_returns_all(monkeypatch):
    rows = [
        _base_row(id="1", transfer_status="auto_paired", description="TRANSFER"),
        _base_row(id="2", transfer_status=None, description="COFFEE"),
    ]
    from app.finance import router as finance_router

    monkeypatch.setattr(finance_router, "_db", lambda: _Client(rows))
    from app.main import app

    _override_auth(app)
    try:
        client = TestClient(app)
        r = client.get("/finance/transactions?exclude_transfers=false")
        assert r.status_code == 200
        ids = {t["id"] for t in r.json()}
        assert ids == {"1", "2"}
    finally:
        app.dependency_overrides.clear()
