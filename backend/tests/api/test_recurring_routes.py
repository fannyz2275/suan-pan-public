from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


def test_scan_reads_beyond_the_first_transaction_page():
    from types import SimpleNamespace
    from app.engine.recurring.router import run_detection
    rows = [{'id':str(i)} for i in range(1001)]
    class Query:
        start, end = 0, 999
        def select(self, *args): return self
        def eq(self, *args): return self
        def gte(self, *args): return self
        def lte(self, *args): return self
        def order(self, *args): return self
        def range(self, start, end): self.start, self.end = start, end; return self
        def execute(self): return SimpleNamespace(data=rows[self.start:self.end+1])
    client = SimpleNamespace(table=lambda name:Query())
    with patch('app.engine.recurring.router.load_rules', return_value=[]), \
         patch('app.engine.recurring.router.upsert_rules'), \
         patch('app.engine.recurring.router.detect_recurring_rules', return_value=[]) as detect:
        run_detection(uuid4(), client)
    assert len(detect.call_args.kwargs['transactions']) == 1001
    assert detect.call_args.kwargs['allow_llm'] is False


class _User:
    def __init__(self, uid):
        self.id = uid
        self.email = "u@test"


def _override_auth(uid):
    from app.auth.middleware import get_current_user
    app.dependency_overrides[get_current_user] = lambda: _User(uid)


def _clear_overrides():
    app.dependency_overrides.clear()


def test_detect_endpoint_returns_rules():
    uid = str(uuid4())
    _override_auth(uid)
    try:
        client = TestClient(app)
        with patch("app.engine.recurring.router._db", return_value=None), \
             patch("app.engine.recurring.router.run_detection", return_value=[]) as mock_run:
            resp = client.post("/engine/recurring/detect", headers={"Authorization": "Bearer fake"})
            assert resp.status_code == 200
            assert resp.json() == {"rules": []}
            mock_run.assert_called_once()
    finally:
        _clear_overrides()


def test_list_rules_endpoint():
    uid = str(uuid4())
    _override_auth(uid)
    try:
        client = TestClient(app)
        with patch("app.engine.recurring.router._db", return_value=None), \
             patch("app.engine.recurring.router.load_rules", return_value=[]):
            resp = client.get("/engine/recurring/rules", headers={"Authorization": "Bearer fake"})
            assert resp.status_code == 200
            assert resp.json() == {"rules": []}
    finally:
        _clear_overrides()


def test_patch_rule_confirm():
    uid = str(uuid4())
    _override_auth(uid)
    try:
        client = TestClient(app)
        rule_id = uuid4()
        with patch("app.engine.recurring.router._db", return_value=None), \
             patch("app.engine.recurring.router._update_rule_status", return_value=None) as mock_update:
            resp = client.patch(
                f"/engine/recurring/rules/{rule_id}",
                json={"action": "confirm"},
                headers={"Authorization": "Bearer fake"},
            )
            assert resp.status_code == 200
            mock_update.assert_called_once()
    finally:
        _clear_overrides()
