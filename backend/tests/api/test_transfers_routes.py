"""Tests for the /engine/transfers/* endpoints using a stubbed Supabase client."""
from fastapi.testclient import TestClient


class _Query:
    def __init__(self, rows):
        self._rows = rows
        self._filters = []
        self._update_payload = None

    def select(self, *_a, **_k):
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in_", col, list(vals)))
        return self

    def gte(self, col, val):
        self._filters.append(("gte", col, val))
        return self

    def order(self, *_a, **_k):
        return self

    def _match(self, row):
        for op, col, val in self._filters:
            v = row.get(col)
            if op == "eq" and v != val:
                return False
            if op == "in_" and v not in val:
                return False
            if op == "gte" and str(v) < str(val):
                return False
        return True

    def execute(self):
        matched = [r for r in self._rows if self._match(r)]
        if self._update_payload is not None:
            for r in matched:
                r.update(self._update_payload)

        class R:
            data = matched

        return R()


class _Client:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Query(self.store[name])


def _override_auth(app, uid="u1"):
    from app.auth.middleware import get_current_user

    class _User:
        id = uid
        email = "u@test"

    app.dependency_overrides[get_current_user] = lambda: _User()


def _patch_db(monkeypatch, store):
    import app.engine.transfers_router as mod

    monkeypatch.setattr(mod, "_db", lambda: _Client(store))


def test_mark_external_sets_status(monkeypatch):
    store = {"transactions": [
        {"id": "t1", "user_id": "u1", "transfer_status": "needs_review", "transfer_group_id": None},
    ]}
    _patch_db(monkeypatch, store)
    from app.main import app

    _override_auth(app)
    try:
        r = TestClient(app).post("/engine/transfers/t1/mark-external")
        assert r.status_code == 200
        assert store["transactions"][0]["transfer_status"] == "external"
    finally:
        app.dependency_overrides.clear()


def test_ownership_enforced(monkeypatch):
    store = {"transactions": [
        {"id": "t1", "user_id": "u_other", "transfer_status": "needs_review"},
    ]}
    _patch_db(monkeypatch, store)
    from app.main import app

    _override_auth(app, uid="u1")
    try:
        r = TestClient(app).post("/engine/transfers/t1/mark-external")
        assert r.status_code == 404
        assert store["transactions"][0]["transfer_status"] == "needs_review"
    finally:
        app.dependency_overrides.clear()


def test_dismiss_unlinks_auto_paired_partner(monkeypatch):
    store = {"transactions": [
        {"id": "t1", "user_id": "u1", "transfer_status": "auto_paired", "transfer_group_id": "g1"},
        {"id": "t2", "user_id": "u1", "transfer_status": "auto_paired", "transfer_group_id": "g1"},
    ]}
    _patch_db(monkeypatch, store)
    from app.main import app

    _override_auth(app)
    try:
        r = TestClient(app).post("/engine/transfers/t1/dismiss")
        assert r.status_code == 200
        by_id = {r["id"]: r for r in store["transactions"]}
        assert by_id["t1"]["transfer_status"] == "dismissed"
        assert by_id["t1"]["transfer_group_id"] is None
        assert by_id["t2"]["transfer_status"] is None
        assert by_id["t2"]["transfer_group_id"] is None
    finally:
        app.dependency_overrides.clear()


def test_link_creates_user_confirmed_pair(monkeypatch):
    store = {"transactions": [
        {"id": "t1", "user_id": "u1", "transfer_status": "needs_review", "transfer_group_id": None},
        {"id": "t2", "user_id": "u1", "transfer_status": None, "transfer_group_id": None},
    ]}
    _patch_db(monkeypatch, store)
    from app.main import app

    _override_auth(app)
    try:
        r = TestClient(app).post("/engine/transfers/t1/link", json={"other_txn_id": "t2"})
        assert r.status_code == 200
        by_id = {row["id"]: row for row in store["transactions"]}
        assert by_id["t1"]["transfer_status"] == "user_confirmed_internal"
        assert by_id["t2"]["transfer_status"] == "user_confirmed_internal"
        assert by_id["t1"]["transfer_group_id"] == by_id["t2"]["transfer_group_id"]
        assert by_id["t1"]["transfer_group_id"] is not None
    finally:
        app.dependency_overrides.clear()


def test_link_rejects_self_link(monkeypatch):
    store = {"transactions": [
        {"id": "t1", "user_id": "u1", "transfer_status": None, "transfer_group_id": None},
    ]}
    _patch_db(monkeypatch, store)
    from app.main import app

    _override_auth(app)
    try:
        r = TestClient(app).post("/engine/transfers/t1/link", json={"other_txn_id": "t1"})
        assert r.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_evidence_link_records_reciprocal_owned_identity(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, 'evidence_advisor_enabled', True)
    store = {'transactions':[
        {'id':'t1','user_id':'u1','account_id':'a','amount':-50,'currency':'USD'},
        {'id':'t2','user_id':'u1','account_id':'b','amount':50,'currency':'USD'}],
        'accounts':[{'id':'a','user_id':'u1'},{'id':'b','user_id':'u1'}]}
    _patch_db(monkeypatch,store)
    from app.main import app
    _override_auth(app)
    try:
        r = TestClient(app).post('/engine/transfers/t1/link',json={'other_txn_id':'t2'})
        assert r.status_code == 200
        assert store['transactions'][0]['counterparty_account_id'] == 'b'
        assert store['transactions'][1]['counterparty_account_id'] == 'a'
    finally: app.dependency_overrides.clear()


def test_confirm_auto_pair_promotes_both_sides(monkeypatch):
    store = {"transactions": [
        {"id": "t1", "user_id": "u1", "transfer_status": "auto_paired", "transfer_group_id": "g1"},
        {"id": "t2", "user_id": "u1", "transfer_status": "auto_paired", "transfer_group_id": "g1"},
    ]}
    _patch_db(monkeypatch, store)
    from app.main import app

    _override_auth(app)
    try:
        r = TestClient(app).post("/engine/transfers/t1/confirm")
        assert r.status_code == 200
        by_id = {row["id"]: row for row in store["transactions"]}
        assert by_id["t1"]["transfer_status"] == "user_confirmed_internal"
        assert by_id["t2"]["transfer_status"] == "user_confirmed_internal"
        assert by_id["t1"]["transfer_group_id"] == "g1"
        # Both sides can appear in the review list; retrying is harmless.
        repeat = TestClient(app).post("/engine/transfers/t2/confirm")
        assert repeat.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_confirm_rejects_non_auto_paired(monkeypatch):
    store = {"transactions": [
        {"id": "t1", "user_id": "u1", "transfer_status": "needs_review", "transfer_group_id": None},
    ]}
    _patch_db(monkeypatch, store)
    from app.main import app

    _override_auth(app)
    try:
        r = TestClient(app).post("/engine/transfers/t1/confirm")
        assert r.status_code == 400
    finally:
        app.dependency_overrides.clear()
