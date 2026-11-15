import math
from unittest.mock import MagicMock
from app.mcp.tools import (
    get_transactions,
    get_spending_by_category,
    detect_transfers,
    update_transaction_category,
    compare_spending_periods,
    bulk_recategorize,
    find_goal_by_name,
    compute_annuity,
)
from app.advisor.categories import ALLOWED_CATEGORIES

USER_ID = "user-123"

def _mock_db(rows):
    db = MagicMock()
    q = db.table.return_value.select.return_value
    q.eq.return_value = q
    q.gte.return_value = q
    q.lte.return_value = q
    q.lt.return_value = q
    q.order.return_value = q
    q.range.return_value = q
    q.execute.return_value.data = rows
    db.table.return_value.update.return_value = q
    return db


def test_get_transactions_returns_list():
    db = _mock_db([{"id": "t1", "date": "2025-12-01", "amount": -50, "category": "Food", "description": "Whole Foods"}])
    result = get_transactions(db, USER_ID, "2025-12-01", "2025-12-31")
    assert isinstance(result, list)
    assert result[0]["id"] == "t1"


def test_get_spending_by_category_aggregates(snapshot_json):
    db = _mock_db([
        {"amount": -100, "category": "Food"},
        {"amount": -200, "category": "Food"},
        {"amount": -50, "category": "Transport"},
    ])
    result = get_spending_by_category(db, USER_ID, "2025-12-01", "2025-12-31")
    # Golden locks total + count + avg_transaction shape across categories.
    assert result == snapshot_json


def test_detect_transfers_finds_zelle():
    db = _mock_db([
        {"id": "t1", "date": "2025-12-01", "description": "Zelle payment to John", "amount": -5000, "category": None},
        {"id": "t2", "date": "2025-12-02", "description": "Coffee shop", "amount": -5, "category": "Food"},
    ])
    result = detect_transfers(db, USER_ID, "2025-12-01", "2025-12-31")
    assert len(result) == 1
    assert result[0]["id"] == "t1"
    assert "zelle" in result[0]["reason"].lower()


def test_bulk_recategorize_dry_run_does_not_update():
    db = _mock_db([
        {"id": "t1", "date": "2025-12-01", "description": "Venmo payment", "amount": -100, "category": "Other"},
    ])
    result = bulk_recategorize(db, USER_ID, "venmo", "Housing", date_from="2025-12-01", date_to="2025-12-31", dry_run=True)
    assert result["updated_count"] == 0
    assert len(result["matched"]) == 1
    assert result["matched"][0]["old_category"] == "Other"
    assert "category" not in result["matched"][0]
    assert result["mode"] == "preview"
    db.table.return_value.update.assert_not_called()


def test_compare_spending_periods_computes_delta(snapshot_json):
    calls = [
        [{"amount": -100, "category": "Food"}, {"amount": -200, "category": "Transport"}],
        [{"amount": -150, "category": "Food"}, {"amount": -180, "category": "Transport"}],
    ]
    call_count = [0]
    db = MagicMock()
    q = db.table.return_value.select.return_value
    q.eq.return_value = q
    q.gte.return_value = q
    q.lte.return_value = q
    q.lt.return_value = q

    def execute():
        m = MagicMock()
        m.data = calls[call_count[0] % 2]
        call_count[0] += 1
        return m

    q.execute.side_effect = execute

    result = compare_spending_periods(db, USER_ID, "2025-11-01", "2025-11-30", "2025-12-01", "2025-12-31")
    # Golden captures per-category breakdown + totals + delta together.
    assert result == snapshot_json


def test_update_transaction_category_success(snapshot_json):
    db = MagicMock()
    # First call (select): return existing transaction
    select_q = MagicMock()
    select_q.eq.return_value = select_q
    select_q.execute.return_value.data = [{"id": "t1", "category": "Other", "description": "Venmo John"}]
    db.table.return_value.select.return_value = select_q

    # Second call (update): chain eq().eq().execute()
    update_q = MagicMock()
    update_q.eq.return_value = update_q
    update_q.execute.return_value.data = [{"id": "t1"}]
    db.table.return_value.update.return_value = update_q

    result = update_transaction_category(db, USER_ID, "t1", "Housing")
    # Golden captures full success-shape: ok, transaction_id, description,
    # old_category, new_category. Future field additions become visible.
    assert result == snapshot_json


def test_update_transaction_category_not_found():
    db = MagicMock()
    select_q = MagicMock()
    select_q.eq.return_value = select_q
    select_q.execute.return_value.data = []
    db.table.return_value.select.return_value = select_q

    result = update_transaction_category(db, USER_ID, "missing", "Housing")
    assert result["ok"] is False
    assert "error" in result


def test_update_transaction_category_rejects_unknown_category():
    db = _mock_db([{"id": "t1", "category": "Food", "description": "X"}])
    result = update_transaction_category(db, USER_ID, "t1", "NotACategory")
    assert result["ok"] is False
    assert result["error"] == "invalid_category"
    assert set(result["allowed"]) == ALLOWED_CATEGORIES


def test_update_transaction_category_accepts_known_category():
    db = _mock_db([{"id": "t1", "category": "Food", "description": "X"}])
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"id": "t1"}]
    result = update_transaction_category(db, USER_ID, "t1", "Shopping")
    assert result["ok"] is True


def test_detect_transfers_uses_limit_and_order():
    db = MagicMock()
    q = db.table.return_value.select.return_value
    q.eq.return_value = q
    q.gte.return_value = q
    q.lte.return_value = q
    q.order.return_value = q
    q.range.return_value = q
    q.execute.return_value.data = []
    detect_transfers(db, USER_ID, "2025-12-01", "2025-12-31", limit=50)
    q.order.assert_called_with("date", desc=True)
    q.range.assert_called_with(0, 49)


def test_get_transactions_min_amount_filters_by_absolute_value():
    """min_amount/max_amount filter on absolute value so income (positive amounts) is included too."""
    db = MagicMock()
    q = db.table.return_value.select.return_value
    q.eq.return_value = q
    q.ilike.return_value = q
    q.gte.return_value = q
    q.lte.return_value = q
    q.order.return_value = q
    q.range.return_value = q
    q.execute.return_value.data = [
        {"id": "a", "amount": -150, "description": "expense", "date": "2025-12-01", "category": "Food", "account_id": "x"},
        {"id": "b", "amount": -50, "description": "small", "date": "2025-12-02", "category": "Food", "account_id": "x"},
        {"id": "c", "amount": 200, "description": "income", "date": "2025-12-03", "category": "Income", "account_id": "x"},
    ]
    rows = get_transactions(db, USER_ID, "2025-12-01", "2025-12-31", min_amount=100)
    assert {r["id"] for r in rows} == {"a", "c"}


def _mock_goals_db(rows):
    db = MagicMock()
    q = db.table.return_value.select.return_value
    q.eq.return_value = q
    q.execute.return_value.data = rows
    return db


def test_find_goal_by_name_exact_match():
    rows = [
        {"id": "g1", "name": "Japan Vacation", "target_amount": 25000, "target_date": "2027-09-01",
         "feasibility_score": None, "status": "on_track", "current_progress": 0},
        {"id": "g2", "name": "Emergency Fund", "target_amount": 12000, "target_date": "2026-01-01",
         "feasibility_score": 80, "status": "on_track", "current_progress": 5000},
    ]
    db = _mock_goals_db(rows)
    result = find_goal_by_name(db, USER_ID, name="Japan Vacation")
    assert result["id"] == "g1"
    assert result["name"] == "Japan Vacation"
    assert result["target_amount"] == 25000
    assert "error" not in result


def test_find_goal_by_name_fuzzy_match():
    rows = [
        {"id": "g1", "name": "Japan Vacation", "target_amount": 25000, "target_date": "2027-09-01",
         "feasibility_score": None, "status": "on_track", "current_progress": 0},
    ]
    db = _mock_goals_db(rows)
    result = find_goal_by_name(db, USER_ID, name="japan vacation trip")
    assert result["id"] == "g1"


def test_find_goal_by_name_not_found_returns_error():
    rows = [
        {"id": "g1", "name": "Emergency Fund", "target_amount": 12000, "target_date": "2026-01-01",
         "feasibility_score": 80, "status": "on_track", "current_progress": 5000},
    ]
    db = _mock_goals_db(rows)
    result = find_goal_by_name(db, USER_ID, name="xyz nonexistent goal qqq")
    assert "error" in result
    assert "all_goal_names" in result
    assert "Emergency Fund" in result["all_goal_names"]


def test_find_goal_by_name_empty_db():
    db = _mock_goals_db([])
    result = find_goal_by_name(db, USER_ID, name="Any Goal")
    assert "error" in result


def test_bulk_recategorize_counts_actual_updates():
    # Two matches: one update returns data, one returns empty (partial failure)
    db = MagicMock()
    q = db.table.return_value.select.return_value
    q.eq.return_value = q
    q.gte.return_value = q
    q.lte.return_value = q
    q.lt.return_value = q
    q.execute.return_value.data = [
        {"id": "t1", "date": "2025-12-01", "description": "Venmo 1", "amount": -100, "category": "Other"},
        {"id": "t2", "date": "2025-12-02", "description": "Venmo 2", "amount": -50, "category": "Other"},
    ]
    # Alternate update outcomes
    update_results = [MagicMock(data=[{"id": "t1"}]), MagicMock(data=[])]
    update_eq_chain = db.table.return_value.update.return_value.eq.return_value.eq
    update_eq_chain.return_value.execute.side_effect = update_results

    result = bulk_recategorize(db, USER_ID, "venmo", "Housing", "2025-12-01", "2025-12-31", dry_run=False)
    assert result["updated_count"] == 1
    assert result["failed_ids"] == ["t2"]
    assert result["mode"] == "executed"


# ---- compute_annuity tests --------------------------------------------------

def test_compute_annuity_months_r8_failing_case():
    """R8 regression: $600/mo @ 7% to $50k → advisor said 61 months, correct is ~68 months."""
    result = compute_annuity(solve_for="months", pmt=600, fv=50000, annual_rate=0.07)
    assert "error" not in result
    assert result["solve_for"] == "months"
    # Exact float answer is 68.11; ceil to 69 months since at 68 months FV is $99 short of $50k
    assert result["months"] == 69
    assert abs(result["months_exact"] - 68.11) < 0.05
    assert result["fv_at_months"] >= 50000


def test_compute_annuity_months_400_pmt():
    """R7/R8 sanity: $400/mo @ 7% to $50k → ~94.15 months, ceil to 95."""
    result = compute_annuity(solve_for="months", pmt=400, fv=50000, annual_rate=0.07)
    assert "error" not in result
    assert result["months"] == 95
    assert abs(result["months_exact"] - 94.15) < 0.05
    assert result["fv_at_months"] >= 50000


def test_compute_annuity_fv_mode():
    """FV mode: $600/mo @ 7% for 68 months → ~$49,900 (just under $50k)."""
    result = compute_annuity(solve_for="fv", pmt=600, months=68, annual_rate=0.07)
    assert "error" not in result
    assert result["solve_for"] == "fv"
    # At exactly 68 months the balance is just under $50k
    assert 49800 < result["fv"] < 50000


# ---- IDOR regression tests --------------------------------------------------

def test_portfolio_tools_reject_unowned_account_id():
    """Each portfolio MCP tool must refuse account_ids the user doesn't own."""
    from app.mcp.tools import portfolio_get_holdings, portfolio_get_exposure, portfolio_get_attribution

    db = MagicMock()
    # accounts query returns empty — pretending the user doesn't own this id
    def table(name):
        t = MagicMock()
        if name == "accounts":
            t.select.return_value.eq.return_value.eq.return_value.in_.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        return t
    db.table.side_effect = table

    out_h = portfolio_get_holdings(db, user_id="user-A", account_id="other-uuid")
    assert out_h == [{"error": "account not found"}]

    out_e = portfolio_get_exposure(db, user_id="user-A", account_id="other-uuid")
    assert out_e == [{"error": "account not found"}]

    out_a = portfolio_get_attribution(
        db, user_id="user-A", from_date="2026-04-01", to_date="2026-05-01",
        account_id="other-uuid",
    )
    assert out_a == {"error": "account not found"}


def test_compute_annuity_fv_mode_confirms_61_months_is_short():
    """Confirms the R8 bug: at 61 months with $600/mo @ 7%, FV is only ~$43,806 not $50k."""
    result = compute_annuity(solve_for="fv", pmt=600, months=61, annual_rate=0.07)
    assert "error" not in result
    assert result["fv"] < 50000
    assert abs(result["fv"] - 43806) < 50


def test_compute_annuity_pmt_mode():
    """PMT mode: to reach $50k in 68 months @ 7% requires ~$601/mo."""
    result = compute_annuity(solve_for="pmt", fv=50000, months=68, annual_rate=0.07)
    assert "error" not in result
    assert result["solve_for"] == "pmt"
    assert abs(result["pmt"] - 601.19) < 0.5


def test_compute_annuity_years_months_string():
    """years_months is formatted correctly for multi-year results."""
    result = compute_annuity(solve_for="months", pmt=600, fv=50000, annual_rate=0.07)
    assert "yr" in result["years_months"]
    assert "mo" in result["years_months"]


def test_compute_annuity_invalid_solve_for():
    result = compute_annuity(solve_for="invalid", annual_rate=0.07)
    assert "error" in result


def test_compute_annuity_missing_pmt_for_months():
    result = compute_annuity(solve_for="months", fv=50000, annual_rate=0.07)
    assert "error" in result


def test_compute_annuity_missing_months_for_fv():
    result = compute_annuity(solve_for="fv", pmt=600, annual_rate=0.07)
    assert "error" in result


def test_compute_annuity_missing_fv_for_pmt():
    result = compute_annuity(solve_for="pmt", months=68, annual_rate=0.07)
    assert "error" in result


def test_compute_annuity_inputs_echoed():
    """Tool result always echoes the inputs so the advisor can cite them."""
    result = compute_annuity(solve_for="months", pmt=500, fv=30000, annual_rate=0.06)
    assert "error" not in result
    assert result["inputs"]["pmt"] == 500
    assert result["inputs"]["fv"] == 30000
    assert result["inputs"]["annual_rate"] == 0.06


# ---- R10-1/R10-3: correct annuity months — perpetuity check was wrong ---------
# The old "perpetuity limit" check (pmt * (1/r) <= fv) was mathematically
# invalid. pmt/r is the PV of a perpetuity, unrelated to the FV of an ordinary
# annuity. For positive pmt/fv/r the formula n = ln(fv*r/pmt+1)/ln(1+r)
# always yields a finite positive answer.

def test_compute_annuity_10_per_month_1M():
    """R10-1: $10/mo @ 7% can reach $1M in ~1096 months (≈91.3 years). No error."""
    result = compute_annuity(solve_for="months", pmt=10, fv=1_000_000, annual_rate=0.07)
    assert "error" not in result, f"unexpected error: {result.get('error')}"
    assert abs(result["months_exact"] - 1095.3) < 1.0, f"expected ~1095, got {result['months_exact']}"
    assert result["months"] > 0
    assert result["fv_at_months"] >= 1_000_000


def test_compute_annuity_10_per_month_2000():
    """R10-3: $10/mo @ 7% can reach $2,000 in ~133 months (≈11 years). No error."""
    result = compute_annuity(solve_for="months", pmt=10, fv=2000, annual_rate=0.07)
    assert "error" not in result, f"unexpected error: {result.get('error')}"
    assert abs(result["months_exact"] - 132.9) < 1.0, f"expected ~133, got {result['months_exact']}"
    assert result["months"] > 0


def test_compute_annuity_pmt_mode_1M_600_months():
    """PMT mode: $1M @ 7% over 600 months.
    Ground truth: PMT = fv * r / ((1+r)^n - 1) = 1e6 * (0.07/12) / ((1+0.07/12)^600 - 1) ≈ $183.55
    """
    result = compute_annuity(solve_for="pmt", fv=1_000_000, months=600, annual_rate=0.07)
    assert "error" not in result
    assert result["solve_for"] == "pmt"
    assert abs(result["pmt"] - 183.55) < 0.5
    assert result["fv"] == 1_000_000
    assert result["months"] == 600


def test_compute_annuity_2000_per_month_1M():
    """R10-1 primary case: $2,000/mo @ 7% → $1M in ~235 months (≈19.6 years). No error."""
    result = compute_annuity(solve_for="months", pmt=2000, fv=1_000_000, annual_rate=0.07)
    assert "error" not in result, f"unexpected error: {result.get('error')}"
    assert abs(result["months_exact"] - 234.7) < 1.0, f"expected ~234.7, got {result['months_exact']}"
    assert result["months"] > 0
    assert "warning" not in result  # well under 1200-month soft cap


def test_compute_annuity_soft_cap_warning():
    """n > 1200 months triggers a warning field but still returns months (no error).
    $5/mo @ 7% -> $1M: ~1214 months (>100 years), triggers soft cap.
    """
    result = compute_annuity(solve_for="months", pmt=5, fv=1_000_000, annual_rate=0.07)
    assert "error" not in result
    assert "months" in result
    assert "warning" in result
    assert result["months_exact"] > 1200


def test_compute_annuity_no_warning_under_cap():
    """n < 1200 months does NOT trigger a warning field."""
    result = compute_annuity(solve_for="months", pmt=2000, fv=1_000_000, annual_rate=0.07)
    assert "error" not in result
    assert "warning" not in result


def test_portfolio_get_holdings_returns_aggregated_household_view():
    from app.mcp.tools import portfolio_get_holdings

    db = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "accounts":
            t.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = [
                {"id": "acc-1"}, {"id": "acc-2"},
            ]
        elif name == "portfolio_snapshots":
            t.select.return_value.eq.return_value.is_.return_value.order.return_value.limit.return_value.execute.return_value.data = [{
                "id": "snap-x", "account_id": "acc-1",
                "snapshot_date": "2026-04-01", "source": "manual",
                "total_value": 10_000, "cash_value": 0,
                "created_at": "2026-04-01T00:00:00Z",
            }]
        elif name == "snapshot_holdings":
            t.select.return_value.eq.return_value.execute.return_value.data = [{
                "snapshot_id": "snap-x", "ticker": "NVDA",
                "quantity": 10, "price": 1000, "market_value": 10_000,
                "cost_basis": None, "unrealized_gain": None,
            }]
        return t
    db.table.side_effect = table

    out = portfolio_get_holdings(db, user_id="u")
    assert isinstance(out, list)
    assert len(out) >= 1
    nvda = next((h for h in out if h["ticker"] == "NVDA"), None)
    assert nvda is not None
    assert nvda["quantity"] >= 10


def test_portfolio_get_exposure_with_look_through():
    from app.mcp.tools import portfolio_get_exposure
    db = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "accounts":
            t.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = [{"id": "acc-1"}]
        elif name == "portfolio_snapshots":
            t.select.return_value.eq.return_value.is_.return_value.order.return_value.limit.return_value.execute.return_value.data = [{
                "id": "snap-x", "account_id": "acc-1",
                "snapshot_date": "2026-04-01", "source": "manual",
                "total_value": 10_000, "cash_value": 0,
                "created_at": "2026-04-01T00:00:00Z",
            }]
        elif name == "snapshot_holdings":
            t.select.return_value.eq.return_value.execute.return_value.data = [
                {"snapshot_id": "snap-x", "ticker": "NVDA", "quantity": 10,
                 "price": 1000, "market_value": 10_000,
                 "cost_basis": None, "unrealized_gain": None},
            ]
        elif name == "security_reference":
            t.select.return_value.in_.return_value.execute.return_value.data = [
                {"ticker": "NVDA", "asset_class": "equity", "sector": "Technology",
                 "region": "US", "look_through": None},
            ]
        return t
    db.table.side_effect = table

    out = portfolio_get_exposure(db, user_id="u", dimension="sector")
    by_label = {s["label"]: s for s in out}
    assert "Technology" in by_label
    assert by_label["Technology"]["market_value"] == 10_000


def test_portfolio_get_attribution_returns_decomposition_and_hints():
    from unittest.mock import patch
    from app.mcp.tools import portfolio_get_attribution

    db = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "accounts":
            t.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = [{"id": "acc-1"}]
        elif name == "portfolio_snapshots":
            t.select.return_value.in_.return_value.is_.return_value.lte.return_value.order.return_value.execute.return_value.data = [
                {"id": "s-start", "account_id": "acc-1", "snapshot_date": "2026-03-01",
                 "source": "manual", "total_value": 10_000, "cash_value": 0,
                 "created_at": "2026-03-01T00:00:00Z"},
                {"id": "s-end", "account_id": "acc-1", "snapshot_date": "2026-04-01",
                 "source": "manual", "total_value": 11_000, "cash_value": 0,
                 "created_at": "2026-04-01T00:00:00Z"},
            ]
        elif name == "snapshot_holdings":
            t.select.return_value.in_.return_value.execute.return_value.data = [
                {"snapshot_id": "s-start", "ticker": "NVDA", "quantity": 10,
                 "price": 1000, "market_value": 10_000, "cost_basis": None, "unrealized_gain": None},
                {"snapshot_id": "s-end", "ticker": "NVDA", "quantity": 10,
                 "price": 1100, "market_value": 11_000, "cost_basis": None, "unrealized_gain": None},
            ]
        elif name == "investment_transactions":
            t.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value.data = []
        elif name == "security_prices":
            t.select.return_value.in_.return_value.gte.return_value.lte.return_value.execute.return_value.data = [
                {"ticker": "NVDA", "date": "2026-03-01", "close": 1000},
                {"ticker": "NVDA", "date": "2026-04-01", "close": 1100},
            ]
        return t
    db.table.side_effect = table

    with patch("app.portfolio.fred.fetch_fred_series", return_value={}):
        out = portfolio_get_attribution(
            db, user_id="u",
            from_date="2026-03-01", to_date="2026-04-01",
        )

    assert out["start_value"] == 10_000
    assert out["end_value"] == 11_000
    assert out["market"] == 1_000
    assert out["contributions"] == 0
    assert isinstance(out["narrative_hints"], list)
    # Market is 1000, which exceeds the 100 threshold → at least one hint should mention market.
    assert any("market" in h.lower() for h in out["narrative_hints"])
