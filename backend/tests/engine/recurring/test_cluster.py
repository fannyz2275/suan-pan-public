from datetime import date

from app.engine.recurring.cluster import build_candidate_clusters


def _txn(tid, desc, amount, d):
    return {"id": tid, "description": desc, "amount": amount, "date": d}


def test_identical_normalized_keys_cluster_together():
    txns = [
        _txn("t1", "POS DEBIT GREYSTAR APTS 01/01", -2800, "2026-01-01"),
        _txn("t2", "POS DEBIT GREYSTAR APTS 02/01", -2800, "2026-02-01"),
        _txn("t3", "POS DEBIT GREYSTAR APTS 03/01", -2800, "2026-03-01"),
    ]
    clusters = build_candidate_clusters(txns, direction="expense")
    assert len(clusters) == 1
    assert len(clusters[0].transaction_ids) == 3


def test_jaccard_merge_on_high_overlap_and_similar_amount():
    # Spotify variations: "spotify premium" and "spotify family" → Jaccard = 1/3 (below 0.6 threshold)
    # but "spotify premium" and "spotify prem" → Jaccard = 1/3 also. Use an actually overlapping pair.
    txns = [
        _txn("t1", "SPOTIFY PREMIUM FAMILY", -15.00, "2026-01-01"),
        _txn("t2", "SPOTIFY PREMIUM FAMILY", -15.00, "2026-02-01"),
        _txn("t3", "SPOTIFY PREMIUM", -15.00, "2026-03-01"),  # shares "spotify" "premium" with above
    ]
    clusters = build_candidate_clusters(txns, direction="expense")
    # Expect one cluster because token Jaccard between "spotify premium family" and "spotify premium"
    # is 2/3 ≥ 0.6 and median amounts within ±10%.
    assert len(clusters) == 1


def test_no_merge_when_amounts_far_apart():
    txns = [
        _txn("t1", "GREYSTAR APTS", -2800, "2026-01-01"),
        _txn("t2", "GREYSTAR APTS", -2800, "2026-02-01"),
        _txn("t3", "GREYSTAR COFFEE", -5, "2026-01-15"),
    ]
    clusters = build_candidate_clusters(txns, direction="expense")
    # Different normalized keys AND amounts far apart → no merge.
    assert len(clusters) == 2


def test_direction_filter_respects_sign():
    txns = [
        _txn("t1", "ACME CORP PAYROLL", 5000, "2026-01-15"),   # income
        _txn("t2", "ACME CORP PAYROLL", 5000, "2026-01-31"),
        _txn("t3", "GREYSTAR APTS", -2800, "2026-01-01"),       # expense
    ]
    income_clusters = build_candidate_clusters(txns, direction="income")
    expense_clusters = build_candidate_clusters(txns, direction="expense")
    assert len(income_clusters) == 1
    assert len(expense_clusters) == 1
    assert income_clusters[0].transaction_ids == ["t1", "t2"]
    assert expense_clusters[0].transaction_ids == ["t3"]


def test_cluster_carries_normalized_key_and_dates():
    txns = [
        _txn("t1", "NETFLIX 01/10", -15.99, "2026-01-10"),
        _txn("t2", "NETFLIX 02/10", -15.99, "2026-02-10"),
    ]
    clusters = build_candidate_clusters(txns, direction="expense")
    assert clusters[0].normalized_key == "netflix"
    assert clusters[0].dates == [date(2026, 1, 10), date(2026, 2, 10)]
    assert clusters[0].amounts == [-15.99, -15.99]
