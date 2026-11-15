"""Unit tests for _summarize_tool_result's bulk_recategorize mode branching."""

from app.advisor.router import _summarize_tool_result


def test_bulk_recategorize_preview_mode():
    result = {
        "mode": "preview",
        "matched": [
            {"id": "a", "description": "Starbucks", "amount": -5.50},
            {"id": "b", "description": "Starbucks Coffee", "amount": -4.75},
            {"id": "c", "description": "STARBUCKS #123", "amount": -6.00},
        ],
    }
    assert _summarize_tool_result("bulk_recategorize", result) == "previewed 3 matches"


def test_bulk_recategorize_preview_mode_empty_matches():
    result = {"mode": "preview", "matched": []}
    assert _summarize_tool_result("bulk_recategorize", result) == "previewed 0 matches"


def test_bulk_recategorize_error_mode():
    result = {"mode": "error", "error": "invalid_category"}
    assert (
        _summarize_tool_result("bulk_recategorize", result)
        == "error: invalid_category"
    )


def test_bulk_recategorize_executed_mode_no_failures():
    result = {
        "mode": "executed",
        "updated_count": 7,
        "failed_ids": [],
    }
    assert (
        _summarize_tool_result("bulk_recategorize", result)
        == "recategorized 7 transactions; 0 failed"
    )


def test_bulk_recategorize_executed_mode_with_failures():
    result = {
        "mode": "executed",
        "updated_count": 5,
        "failed_ids": ["tx-1", "tx-2"],
    }
    assert (
        _summarize_tool_result("bulk_recategorize", result)
        == "recategorized 5 transactions; 2 failed"
    )


def test_bulk_recategorize_default_mode_is_executed():
    """If `mode` is missing, fall back to the executed-mode summary."""
    result = {"updated_count": 3, "failed_ids": []}
    assert (
        _summarize_tool_result("bulk_recategorize", result)
        == "recategorized 3 transactions; 0 failed"
    )
