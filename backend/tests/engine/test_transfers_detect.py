from app.engine.transfers import detect_pairs_and_orphans, ScanDecision


def _txn(**overrides):
    base = {
        "id": "t1",
        "account_id": "a1",
        "date": "2026-04-10",
        "description": "TRANSFER TO FIDELITY",
        "amount": -2000.00,
        "transfer_status": None,
        "transfer_group_id": None,
    }
    base.update(overrides)
    base.update(user_id='u1', currency='USD', counterparty_provenance='user_confirmed',
                counterparty_account_id='a2' if base['account_id'] == 'a1' else 'a1')
    return base


def test_amount_match_within_window_auto_pairs():
    t1 = _txn(id="t1", account_id="a1", date="2026-04-10", amount=-2000.00)
    t2 = _txn(id="t2", account_id="a2", date="2026-04-12", amount=2000.00)
    decisions = detect_pairs_and_orphans([t1, t2])
    assert len(decisions) == 2
    assert {d.txn_id for d in decisions} == {"t1", "t2"}
    assert all(d.new_status == "auto_paired" for d in decisions)
    assert decisions[0].new_group_id == decisions[1].new_group_id
    assert decisions[0].new_group_id is not None


def test_amount_match_outside_window_does_not_pair():
    t1 = _txn(id="t1", account_id="a1", date="2026-04-01", amount=-2000.00)
    t2 = _txn(id="t2", account_id="a2", date="2026-04-10", amount=2000.00)  # 9 days apart
    decisions = detect_pairs_and_orphans([t1, t2])
    # Both have the keyword "TRANSFER" so they become orphans, not paired
    assert all(d.new_status == "needs_review" for d in decisions)


def test_same_account_does_not_pair():
    t1 = _txn(id="t1", account_id="a1", amount=-2000.00)
    t2 = _txn(id="t2", account_id="a1", amount=2000.00)
    decisions = detect_pairs_and_orphans([t1, t2])
    # Must be different accounts — same account cannot be a transfer leg
    assert all(d.new_status == "needs_review" for d in decisions)


def test_ambiguous_match_does_not_pair():
    t1 = _txn(id="t1", account_id="a1", date="2026-04-10", amount=-2000.00)
    t2 = _txn(id="t2", account_id="a2", date="2026-04-11", amount=2000.00)
    t3 = _txn(id="t3", account_id="a2", date="2026-04-11", amount=2000.00)
    decisions = detect_pairs_and_orphans([t1, t2, t3])
    # Ambiguous: two candidates match t1. Leave as orphan.
    assert all(d.new_status == "needs_review" for d in decisions)


def test_keyword_only_orphan_gets_needs_review():
    t1 = _txn(id="t1", description="ACH WITHDRAWAL", amount=-500.00)
    decisions = detect_pairs_and_orphans([t1])
    assert len(decisions) == 1
    assert decisions[0].new_status == "needs_review"


def test_no_keyword_no_match_is_ignored():
    t1 = _txn(id="t1", description="WHOLE FOODS #123", amount=-82.50)
    decisions = detect_pairs_and_orphans([t1])
    assert decisions == []


def test_frozen_statuses_are_skipped():
    for frozen in ("auto_paired", "user_confirmed_internal", "external", "dismissed"):
        t1 = _txn(id="t1", transfer_status=frozen, amount=-2000.00)
        t2 = _txn(id="t2", account_id="a2", amount=2000.00, transfer_status=None)
        decisions = detect_pairs_and_orphans([t1, t2])
        # t1 is frozen and must not be touched; t2 alone is a keyword orphan
        assert all(d.txn_id == "t2" for d in decisions)


def test_needs_review_rows_are_reevaluated():
    # An existing orphan that now has a match must become auto_paired
    t1 = _txn(id="t1", amount=-2000.00, transfer_status="needs_review")
    t2 = _txn(id="t2", account_id="a2", amount=2000.00, transfer_status=None)
    decisions = detect_pairs_and_orphans([t1, t2])
    assert {d.new_status for d in decisions} == {"auto_paired"}


def test_amount_match_uses_cents_exact():
    t1 = _txn(id="t1", amount=-2000.01, description="TRANSFER")
    t2 = _txn(id="t2", account_id="a2", amount=2000.00, description="TRANSFER")
    decisions = detect_pairs_and_orphans([t1, t2])
    # Cents differ → no pair; both keyword orphans
    assert all(d.new_status == "needs_review" for d in decisions)


def test_ambiguous_match_is_order_independent():
    # Regression guard for a naive single-pass pairing loop: if t2 and t3 both match t1,
    # a naive loop that consumes the first match it finds would incorrectly pair (t2, t1)
    # when t2 is processed before t1 — even though t1 has two candidates and is ambiguous.
    t1 = _txn(id="t1", account_id="a1", date="2026-04-10", amount=-2000.00)
    t2 = _txn(id="t2", account_id="a2", date="2026-04-11", amount=2000.00)
    t3 = _txn(id="t3", account_id="a2", date="2026-04-11", amount=2000.00)
    # Feed in the order that breaks the naive approach: t2 first.
    decisions = detect_pairs_and_orphans([t2, t1, t3])
    assert all(d.new_status == "needs_review" for d in decisions)


def test_accepts_decimal_amounts():
    # Real DB rows come back with Decimal amounts; make sure pairing still works.
    from decimal import Decimal as D

    t1 = _txn(id="t1", account_id="a1", date="2026-04-10", amount=D("-2000.00"))
    t2 = _txn(id="t2", account_id="a2", date="2026-04-12", amount=D("2000.00"))
    decisions = detect_pairs_and_orphans([t1, t2])
    assert {d.new_status for d in decisions} == {"auto_paired"}
