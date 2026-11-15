"""Tests for the unified /import/statements router."""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client_with_user():
    from app.auth.middleware import get_current_user

    fake_user = MagicMock()
    fake_user.id = uuid4()
    app.dependency_overrides[get_current_user] = lambda: fake_user
    yield TestClient(app), fake_user
    app.dependency_overrides.clear()


def _accounts_select(rows: list[dict]):
    """Build a chain mock that returns `rows` from accounts select."""
    chain = MagicMock()
    chain.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = rows
    return chain


def _make_db(account_rows_by_id: dict[str, dict], *, txn_dup: bool = False, needs_review_count: int = 0):
    """Generic DB mock keyed by account_id. Tracks inserted transactions in
    `db._txn_inserts` for assertions."""

    inserts: list[dict] = []

    def _table(name: str):
        t = MagicMock()
        if name == "accounts":
            # _load_account: .select.eq(id, ...).eq(user_id, ...).limit(1).execute().data
            def _select(*_a, **_kw):
                inner = MagicMock()
                def _eq_id(field, value):
                    matched_row = account_rows_by_id.get(value)
                    inner2 = MagicMock()
                    inner2.eq.return_value.limit.return_value.execute.return_value.data = (
                        [matched_row] if matched_row else []
                    )
                    return inner2
                inner.eq.side_effect = _eq_id
                return inner
            t.select.side_effect = _select

            # update path used by bank confirm
            t.update.return_value.eq.return_value.execute.return_value.data = []
        elif name == "transactions":
            # Dedup probe: .select.eq(...)... -> .data
            sel = MagicMock()
            sel.eq.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = (
                [{"id": "exists"}] if txn_dup else []
            )
            # needs_review count probe: .select("id", count="exact").eq.eq.execute()
            count_resp = MagicMock()
            count_resp.count = needs_review_count
            count_resp.data = []
            sel.eq.return_value.eq.return_value.execute.return_value = count_resp
            t.select.return_value = sel

            def _insert(payload):
                inserts.append(payload)
                rv = MagicMock()
                rv.execute.return_value.data = [payload]
                return rv
            t.insert.side_effect = _insert
        elif name == "account_balance_history":
            t.insert.return_value.execute.return_value.data = [{}]
        return t

    db = MagicMock()
    db.table.side_effect = _table
    db._txn_inserts = inserts  # type: ignore[attr-defined]
    return db


def _file(name: str, content: bytes = b"sample statement text"):
    return (name, io.BytesIO(content), "text/plain")


@pytest.mark.parametrize('text', ['Account number: 11112222\nAccount number: 33334444',
                                 'Account ending in 9999',
                                 'Account number: 11112222\nAccount number: 33332222'])
def test_single_account_rejects_conflicting_identifiers(text):
    from app.imports.statements_router import _check_account_identifiers
    with pytest.raises(ValueError, match='multiple-account mode'):
        _check_account_identifiers(text, {'account_number_last4': '2222'})


def test_single_account_allows_repeated_matching_identifier():
    from app.imports.statements_router import _check_account_identifiers
    _check_account_identifiers('Account number: 11112222\nAccount ending in 2222', {'account_number_last4': '2222'})


def test_detect_parses_each_section_separately_and_scopes_account_lookup(client_with_user):
    client, user = client_with_user
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "a", "name": "Chase Checking", "type": "checking", "account_number_last4": "1234"},
        {"id": "b", "name": "Chase Savings", "type": "savings", "account_number_last4": "5678"},
    ]
    sections = [
        {"institution": "Chase", "type": "checking", "last4": "1234", "text": "first account", "ranges": [[1, 2]]},
        {"institution": "Chase", "type": "savings", "last4": "5678", "text": "second account", "ranges": [[3, 4]]},
    ]
    from app.imports.statements_router import BankPreviewBody
    with patch('app.imports.statements_router.get_admin_db', return_value=db), \
         patch('app.imports.statements_router.detect_sections', return_value=sections), \
         patch('app.imports.statements_router._bank_preview', return_value=BankPreviewBody(balance=10, transactions=[])) as parse:
        response = client.post('/import/statements/detect', files=[('files', _file('combined.txt'))])
    assert response.status_code == 200
    assert [g['account_id'] for g in response.json()['groups']] == ['a', 'b']
    assert [call.args[0] for call in parse.call_args_list] == ['first account', 'second account']
    db.table.return_value.select.return_value.eq.assert_called_once_with('user_id', str(user.id))
    db.table.return_value.insert.assert_not_called()


def test_detect_does_not_return_partial_success_or_raw_provider_error(client_with_user):
    client, _ = client_with_user
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    with patch('app.imports.statements_router.get_admin_db', return_value=db), \
         patch('app.imports.statements_router.detect_sections', side_effect=ValueError('secret statement text')):
        response = client.post('/import/statements/detect', files=[('files', _file('combined.txt'))])
    assert response.status_code == 200
    assert response.json()['groups'][0]['error_code'] == 'boundaries'
    assert 'secret' not in response.text


def test_detect_keeps_successful_section_when_another_parse_fails(client_with_user):
    client, _ = client_with_user
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    from app.imports.statements_router import BankPreviewBody
    sections = [{'institution': 'Chase', 'type': 'checking', 'last4': None,
                 'text': str(i), 'ranges': [[i + 1, i + 1]]} for i in range(2)]
    with patch('app.imports.statements_router.get_admin_db', return_value=db), \
         patch('app.imports.statements_router.detect_sections', return_value=sections), \
         patch('app.imports.statements_router._bank_preview', side_effect=[BankPreviewBody(balance=10, transactions=[]), ValueError('private data')]):
        response = client.post('/import/statements/detect', files=[('files', _file('combined.txt'))])
    groups = response.json()['groups']
    assert groups[0]['preview']['balance'] == 10
    assert groups[1]['error_code'] == 'section_parse'
    assert groups[1]['preview'] is None
    assert 'private data' not in response.text


@pytest.mark.parametrize('confirmed,detected_type', [(False, 'checking'), (True, 'savings')])
def test_detected_destination_must_be_confirmed_and_type_matched(client_with_user, confirmed, detected_type):
    client, _ = client_with_user
    account = {'id': 'a', 'name': 'Checking', 'type': 'checking', 'balance': 0}
    db = _make_db({'a': account})
    with patch('app.imports.statements_router.get_admin_db', return_value=db), \
         patch('app.imports.statements_router.scan_transfers_for_user'), \
         patch('app.imports.statements_router._count_new_review_candidates', return_value=0):
        result = client.post('/import/statements/confirm', json={'groups': [{
            'row_id': 'r', 'account_id': 'a', 'kind': 'bank', 'balance': 10,
            'transactions': [], 'detected_type': detected_type, 'destination_confirmed': confirmed,
        }]})
    assert result.json()['saved'][0]['error']
    assert not db._txn_inserts


def test_preview_dispatches_by_account_type(client_with_user):
    client, user = client_with_user
    aid_checking = str(uuid4())
    aid_brokerage = str(uuid4())
    accounts = {
        aid_checking: {"id": aid_checking, "name": "Chase Checking", "type": "checking",
                       "balance": 1000.0, "balance_updated_at": None, "created_at": None,
                       "account_number_last4": None},
        aid_brokerage: {"id": aid_brokerage, "name": "Fidelity", "type": "brokerage",
                        "balance": 0, "balance_updated_at": None, "created_at": None,
                        "account_number_last4": None},
    }

    with patch("app.imports.statements_router.get_admin_db", return_value=_make_db(accounts)), \
         patch("app.imports.statements_router.parse_accounts_from_text",
               return_value=[{"name": "Chase Checking", "type": "checking",
                              "balance": 1234.56, "statement_date": "2026-02-28",
                              "account_number_last4": "1234"}]), \
         patch("app.imports.statements_router.parse_transactions_from_text",
               return_value=[{"date": "2026-02-10", "description": "Whole Foods",
                              "amount": -50.0, "category": "food"}]), \
         patch("app.imports.statements_router.parse_investment_statement",
               return_value={"statement_date": "2026-03-31", "cash_value": 100,
                             "holdings": [{"ticker": "VTI", "quantity": 10,
                                           "price": 234.18, "market_value": 2341.8}],
                             "investment_transactions": [],
                             "total_value_reported": 2441.8,
                             "account_hint": "...4567"}):
        resp = client.post(
            "/import/statements/preview",
            data={"rows": json.dumps([
                {"row_id": "r1", "account_id": aid_checking},
                {"row_id": "r2", "account_id": aid_brokerage},
            ])},
            files=[
                ("r1", _file("chase.txt")),
                ("r2", _file("fidelity.txt")),
            ],
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    groups = body["groups"]
    assert len(groups) == 2

    bank, inv = groups[0], groups[1]
    assert bank["row_id"] == "r1"
    assert bank["kind"] == "bank"
    assert bank["error"] is None
    assert bank["preview"]["balance"] == 1234.56
    assert bank["preview"]["statement_date"] == "2026-02-28"
    assert len(bank["preview"]["transactions"]) == 1

    assert inv["row_id"] == "r2"
    assert inv["kind"] == "investment"
    assert inv["error"] is None
    assert inv["preview"]["statement_date"] == "2026-03-31"
    assert inv["preview"]["holdings"][0]["ticker"] == "VTI"
    assert inv["preview"]["total_value_reported"] == 2441.8


def test_preview_per_row_error_does_not_fail_whole_call(client_with_user):
    client, user = client_with_user
    aid_a = str(uuid4())
    aid_b = str(uuid4())
    accounts = {
        aid_a: {"id": aid_a, "name": "A", "type": "checking",
                "balance": 0, "balance_updated_at": None, "created_at": None,
                "account_number_last4": None},
        aid_b: {"id": aid_b, "name": "B", "type": "checking",
                "balance": 0, "balance_updated_at": None, "created_at": None,
                "account_number_last4": None},
    }

    # Row A raises on parse, row B succeeds.
    def _accounts_side_effect(text):
        if "boom" in text:
            raise ValueError("parser exploded")
        return [{"name": "B", "type": "checking", "balance": 50.0}]

    with patch("app.imports.statements_router.get_admin_db", return_value=_make_db(accounts)), \
         patch("app.imports.statements_router.parse_accounts_from_text",
               side_effect=_accounts_side_effect), \
         patch("app.imports.statements_router.parse_transactions_from_text",
               return_value=[]):
        resp = client.post(
            "/import/statements/preview",
            data={"rows": json.dumps([
                {"row_id": "rA", "account_id": aid_a},
                {"row_id": "rB", "account_id": aid_b},
            ])},
            files=[
                ("rA", _file("a.txt", b"boom file")),
                ("rB", _file("b.txt", b"ok file")),
            ],
        )

    assert resp.status_code == 200
    groups = resp.json()["groups"]
    assert len(groups) == 2
    by_row = {g["row_id"]: g for g in groups}
    assert by_row["rA"]["error"] is not None
    assert by_row["rA"]["preview"] is None
    assert by_row["rB"]["error"] is None
    assert by_row["rB"]["preview"]["balance"] == 50.0


def test_preview_rejects_other_users_account(client_with_user):
    client, _ = client_with_user
    aid = str(uuid4())
    # Empty accounts map -> _load_account raises 404
    with patch("app.imports.statements_router.get_admin_db", return_value=_make_db({})):
        resp = client.post(
            "/import/statements/preview",
            data={"rows": json.dumps([{"row_id": "r1", "account_id": aid}])},
            files=[("r1", _file("x.txt"))],
        )

    assert resp.status_code == 200  # per-row errors don't fail whole call
    g = resp.json()["groups"][0]
    assert "not found" in (g["error"] or "").lower()


def test_confirm_bank_inserts_transactions_with_account_id(client_with_user):
    client, user = client_with_user
    aid = str(uuid4())
    accounts = {aid: {"id": aid, "name": "Chase", "type": "checking",
                      "balance": 100.0, "balance_updated_at": None,
                      "created_at": "2026-01-01T00:00:00Z",
                      "account_number_last4": None}}

    db = _make_db(accounts, txn_dup=False, needs_review_count=3)

    with patch("app.imports.statements_router.get_admin_db", return_value=db), \
         patch("app.imports.statements_router.scan_transfers_for_user", return_value=None) as scan_mock, \
         patch("app.imports.statements_router.record_history", return_value=None):
        resp = client.post(
            "/import/statements/confirm",
            json={"groups": [{
                "row_id": "r1", "account_id": aid, "kind": "bank",
                "balance": 1500.0, "statement_date": "2026-02-28",
                "transactions": [
                    {"date": "2026-02-10", "description": "Salary", "amount": 5000.0, "category": "income"},
                    {"date": "2026-02-12", "description": "Groceries", "amount": -120.0, "category": "food"},
                ],
            }]},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["transfer_candidates_added"] == 3
    saved = body["saved"][0]
    assert saved["transactions_created"] == 2
    assert saved["transactions_skipped"] == 0
    assert saved["balance_updated"] is True

    # Every inserted transaction must carry account_id.
    assert len(db._txn_inserts) == 2
    for ins in db._txn_inserts:
        assert ins["account_id"] == aid
        assert ins["source"] == "manual"

    scan_mock.assert_called_once()


def test_confirm_bank_idempotent_when_transactions_duplicate(client_with_user):
    client, _ = client_with_user
    aid = str(uuid4())
    accounts = {aid: {"id": aid, "name": "Chase", "type": "checking",
                      "balance": 100.0, "balance_updated_at": None,
                      "created_at": "2026-01-01T00:00:00Z",
                      "account_number_last4": None}}

    db = _make_db(accounts, txn_dup=True, needs_review_count=0)

    with patch("app.imports.statements_router.get_admin_db", return_value=db), \
         patch("app.imports.statements_router.scan_transfers_for_user", return_value=None), \
         patch("app.imports.statements_router.record_history", return_value=None):
        resp = client.post(
            "/import/statements/confirm",
            json={"groups": [{
                "row_id": "r1", "account_id": aid, "kind": "bank",
                "balance": 100.0,
                "transactions": [
                    {"date": "2026-02-10", "description": "Salary",
                     "amount": 5000.0, "category": "income"},
                ],
            }]},
        )

    assert resp.status_code == 200
    saved = resp.json()["saved"][0]
    assert saved["transactions_created"] == 0
    assert saved["transactions_skipped"] == 1
    # Same balance value -> not "changed" (balance_updated False).
    assert saved["balance_updated"] is False
    assert len(db._txn_inserts) == 0


def test_confirm_investment_calls_snapshot_writer(client_with_user):
    client, user = client_with_user
    aid = str(uuid4())
    accounts = {aid: {"id": aid, "name": "Fidelity", "type": "brokerage",
                      "balance": 0, "balance_updated_at": None,
                      "created_at": None, "account_number_last4": None}}
    snap_id = str(uuid4())

    with patch("app.imports.statements_router.get_admin_db", return_value=_make_db(accounts)), \
         patch("app.imports.statements_router.scan_transfers_for_user", return_value=None), \
         patch("app.imports.statements_router.snapshots.create_statement_snapshot",
               return_value={"id": snap_id}) as create_mock:
        resp = client.post(
            "/import/statements/confirm",
            json={"groups": [{
                "row_id": "r1", "account_id": aid, "kind": "investment",
                "statement_date": "2026-03-31", "cash_value": 100.0,
                "holdings": [{"ticker": "VTI", "quantity": 10, "price": 234.18, "market_value": 2341.8}],
                "investment_transactions": [{"date": "2026-03-15", "type": "buy",
                                              "ticker": "VTI", "quantity": 1,
                                              "price": 234.0, "amount": -234.0}],
            }]},
        )

    assert resp.status_code == 200, resp.text
    saved = resp.json()["saved"][0]
    assert saved["snapshot_id"] == snap_id
    assert saved["holdings_count"] == 1
    assert saved["txns_count"] == 1
    create_mock.assert_called_once()


def test_confirm_rejects_wrong_account_kind(client_with_user):
    client, _ = client_with_user
    aid = str(uuid4())
    accounts = {aid: {"id": aid, "name": "Chase", "type": "checking",
                      "balance": 0, "balance_updated_at": None,
                      "created_at": None, "account_number_last4": None}}

    with patch("app.imports.statements_router.get_admin_db", return_value=_make_db(accounts)), \
         patch("app.imports.statements_router.scan_transfers_for_user", return_value=None):
        resp = client.post(
            "/import/statements/confirm",
            json={"groups": [{
                "row_id": "r1", "account_id": aid, "kind": "investment",
                "statement_date": "2026-03-31", "cash_value": 0,
                "holdings": [], "investment_transactions": [],
            }]},
        )

    assert resp.status_code == 200
    saved = resp.json()["saved"][0]
    assert saved["error"] is not None
    assert "investment" in saved["error"].lower()


def test_confirm_runs_transfer_scan_and_reports_count(client_with_user):
    client, user = client_with_user
    aid = str(uuid4())
    accounts = {aid: {"id": aid, "name": "Chase", "type": "checking",
                      "balance": 0, "balance_updated_at": None,
                      "created_at": None, "account_number_last4": None}}

    db = _make_db(accounts, needs_review_count=12)

    with patch("app.imports.statements_router.get_admin_db", return_value=db), \
         patch("app.imports.statements_router.scan_transfers_for_user",
               return_value=None) as scan_mock, \
         patch("app.imports.statements_router.record_history", return_value=None):
        resp = client.post(
            "/import/statements/confirm",
            json={"groups": [{
                "row_id": "r1", "account_id": aid, "kind": "bank",
                "balance": 0, "transactions": [],
            }]},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["transfer_candidates_added"] == 12
    scan_mock.assert_called_once_with(db, user_id=str(user.id))


def test_preview_validates_row_count(client_with_user):
    client, _ = client_with_user
    rows = [{"row_id": f"r{i}", "account_id": str(uuid4())} for i in range(11)]
    resp = client.post(
        "/import/statements/preview",
        data={"rows": json.dumps(rows)},
        files=[("r0", _file("a.txt"))],
    )
    assert resp.status_code == 400
    assert "max" in resp.json()["detail"].lower()
