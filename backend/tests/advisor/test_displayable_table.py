"""Unit tests for _build_displayable_table — the inline-card payload."""

from app.advisor.router import _build_displayable_table, DISPLAYABLE_TABLE_MIN_ROWS


def _txn(date: str, desc: str, amount: float, category: str = "Bills") -> dict:
    return {"date": date, "description": desc, "amount": amount, "category": category}


def test_get_transactions_under_threshold_returns_none():
    rows = [_txn(f"2025-12-{i:02d}", f"Shop {i}", -10.0) for i in range(1, DISPLAYABLE_TABLE_MIN_ROWS)]
    assert _build_displayable_table("get_transactions", rows, {}) is None


def test_get_transactions_at_threshold_returns_table():
    rows = [_txn(f"2025-12-{i:02d}", f"Shop {i}", -10.0) for i in range(1, DISPLAYABLE_TABLE_MIN_ROWS + 1)]
    table = _build_displayable_table("get_transactions", rows, {})
    assert table is not None
    assert table["title"].startswith("Transactions")
    assert "transactions" in table["summary"]
    assert len(table["rows"]) == DISPLAYABLE_TABLE_MIN_ROWS
    assert {c["key"] for c in table["columns"]} == {"date", "description", "category", "amount"}


def test_get_transactions_includes_pattern_in_title():
    rows = [_txn(f"2025-12-{i:02d}", "Verizon", -100.0) for i in range(1, DISPLAYABLE_TABLE_MIN_ROWS + 1)]
    table = _build_displayable_table(
        "get_transactions", rows,
        {"description_pattern": "verizon", "date_from": "2025-01-01", "date_to": "2025-12-31"},
    )
    assert table is not None
    assert "verizon" in table["title"].lower()
    assert "2025-01-01" in table["title"]


def test_list_recurring_rules_below_threshold_returns_none():
    rules = [
        {"keyword": f"M{i}", "frequency": "monthly", "monthly_equivalent": 30.0, "status": "user_confirmed"}
        for i in range(DISPLAYABLE_TABLE_MIN_ROWS - 1)
    ]
    assert _build_displayable_table("list_recurring_rules", rules, None) is None


def test_list_recurring_rules_at_threshold_returns_table():
    rules = [
        {"keyword": f"M{i}", "frequency": "monthly", "monthly_equivalent": 30.0, "status": "user_confirmed"}
        for i in range(DISPLAYABLE_TABLE_MIN_ROWS)
    ]
    table = _build_displayable_table("list_recurring_rules", rules, None)
    assert table is not None
    assert "rules" in table["summary"]
    assert len(table["rows"]) == DISPLAYABLE_TABLE_MIN_ROWS


def test_detect_transfers_at_threshold_returns_table():
    transfers = [
        {"date": f"2025-12-{i:02d}", "description": f"Zelle {i}", "amount": -50.0, "reason": "keyword"}
        for i in range(1, DISPLAYABLE_TABLE_MIN_ROWS + 1)
    ]
    table = _build_displayable_table("detect_transfers", transfers, {})
    assert table is not None
    assert table["title"].startswith("Likely")
    assert len(table["rows"]) == DISPLAYABLE_TABLE_MIN_ROWS


def test_unknown_tool_returns_none():
    assert _build_displayable_table("monte_carlo", {"p50": 1}, None) is None


def test_unexpected_shape_returns_none_silently():
    # Defensive: dict instead of list shouldn't crash.
    assert _build_displayable_table("get_transactions", {"oops": True}, None) is None
