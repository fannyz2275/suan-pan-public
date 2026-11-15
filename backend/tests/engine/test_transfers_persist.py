"""Tests for scan_transfers_for_user using an in-memory stub of Supabase."""
from datetime import date, timedelta

from app.engine import transfers as tmod


class StubTable:
    """Minimal Supabase .table() builder covering our read/update patterns."""

    def __init__(self, rows, on_update=None):
        self.rows = rows
        self._filters = []
        self._on_update = on_update
        self._update_payload = None

    def select(self, *_args, **_kwargs):
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def gte(self, col, val):
        self._filters.append(("gte", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in_", col, list(vals)))
        return self

    def _match(self, row):
        for op, col, val in self._filters:
            if op == "eq" and row.get(col) != val:
                return False
            if op == "gte" and str(row.get(col)) < str(val):
                return False
            if op == "in_" and row.get(col) not in val:
                return False
        return True

    def execute(self):
        if self._update_payload is not None:
            affected = [r for r in self.rows if self._match(r)]
            for r in affected:
                r.update(self._update_payload)
            if self._on_update:
                self._on_update(self._update_payload, affected)

            class R:
                data = affected

            return R()

        class R:
            data = [r for r in self.rows if self._match(r)]

        return R()


class StubDB:
    def __init__(self, rows):
        self.rows = rows
        self.update_calls = []

    def table(self, _name):
        return StubTable(
            self.rows,
            on_update=lambda payload, affected: self.update_calls.append(
                (payload, [r["id"] for r in affected])
            ),
        )


def _row(**kw):
    base = {
        "id": "t1",
        "user_id": "u1",
        "account_id": "a1",
        "date": (date.today() - timedelta(days=2)).isoformat(),
        "description": "TRANSFER",
        "amount": -1000.00,
        "transfer_status": None,
        "transfer_group_id": None,
    }
    base.update(kw)
    base.update(currency='USD', counterparty_provenance='user_confirmed',
                counterparty_account_id='acc2' if base['account_id'] == 'acc1' else 'acc1')
    return base


def test_scan_pairs_and_persists():
    rows = [
        _row(id="a", account_id="acc1", amount=-500.00, description="TRANSFER OUT"),
        _row(id="b", account_id="acc2", amount=500.00, description="TRANSFER IN"),
    ]
    db = StubDB(rows)
    result = tmod.scan_transfers_for_user(db, user_id="u1")
    assert result.paired_count == 1
    assert result.orphan_count == 0
    assert rows[0]["transfer_status"] == "auto_paired"
    assert rows[1]["transfer_status"] == "auto_paired"
    assert rows[0]["transfer_group_id"] == rows[1]["transfer_group_id"]
    assert rows[0]["transfer_group_id"] is not None


def test_scan_respects_frozen_statuses():
    rows = [
        _row(id="a", transfer_status="dismissed", amount=-500.00),
        _row(id="b", account_id="acc2", amount=500.00, description="TRANSFER"),
    ]
    db = StubDB(rows)
    tmod.scan_transfers_for_user(db, user_id="u1")
    assert rows[0]["transfer_status"] == "dismissed"
    assert rows[1]["transfer_status"] == "needs_review"


def test_scan_is_idempotent():
    rows = [
        _row(id="a", account_id="acc1", amount=-500.00, description="TRANSFER"),
        _row(id="b", account_id="acc2", amount=500.00, description="TRANSFER"),
    ]
    db = StubDB(rows)
    tmod.scan_transfers_for_user(db, user_id="u1")
    group_after_first = rows[0]["transfer_group_id"]
    r2 = tmod.scan_transfers_for_user(db, user_id="u1")
    assert rows[0]["transfer_group_id"] == group_after_first
    assert r2.paired_count == 0
    assert r2.orphan_count == 0


def test_scan_only_reads_window():
    rows = [_row(id="a")]
    db = StubDB(rows)
    seen = []
    orig_gte = StubTable.gte

    def spy(self, col, val):
        seen.append((col, val))
        return orig_gte(self, col, val)

    StubTable.gte = spy
    try:
        tmod.scan_transfers_for_user(db, user_id="u1", window_days=30)
    finally:
        StubTable.gte = orig_gte
    assert any(col == "date" for col, _ in seen)


def test_scan_filters_by_user_id():
    rows = [
        _row(id="mine", user_id="u1", account_id="acc1", amount=-500.00, description="TRANSFER"),
        _row(id="theirs", user_id="u2", account_id="acc2", amount=500.00, description="TRANSFER"),
    ]
    db = StubDB(rows)
    tmod.scan_transfers_for_user(db, user_id="u1")
    # u2's row must not be touched and must not pair with u1's row
    assert rows[1]["transfer_status"] is None
    assert rows[0]["transfer_status"] == "needs_review"


def test_orphan_count_reports_keyword_flagged_rows():
    rows = [
        _row(id="a", account_id="acc1", amount=-500.00, description="ACH WITHDRAWAL"),
    ]
    db = StubDB(rows)
    result = tmod.scan_transfers_for_user(db, user_id="u1")
    assert result.paired_count == 0
    assert result.orphan_count == 1
    assert rows[0]["transfer_status"] == "needs_review"
