from datetime import date

import pytest

from app.imports.filename_dates import parse_statement_date_from_filename


@pytest.mark.parametrize("name,expected", [
    # Full ISO dates
    ("statement-2024-03-15.pdf", date(2024, 3, 15)),
    ("statement_2024_03_15.pdf", date(2024, 3, 15)),
    ("20240315_chase.pdf", date(2024, 3, 15)),
    ("chase.20240315.pdf", date(2024, 3, 15)),
    # Year + month -> end of month
    ("chase_2024_03.pdf", date(2024, 3, 31)),
    ("chase-2024-02.pdf", date(2024, 2, 29)),  # leap year
    # MM-DD-YYYY (US)
    ("stmt-03-15-2024.pdf", date(2024, 3, 15)),
    ("eStmt_03152024.pdf", date(2024, 3, 15)),
    # Month name
    ("Mar2024.pdf", date(2024, 3, 31)),
    ("statement_March_2024.csv", date(2024, 3, 31)),
    ("Sept-2024.pdf", date(2024, 9, 30)),
    # Quarters
    ("2024_Q1_brokerage.csv", date(2024, 3, 31)),
    ("2024-Q3-statement.pdf", date(2024, 9, 30)),
    ("Q4_2024_summary.pdf", date(2024, 12, 31)),
])
def test_recognizes_common_patterns(name: str, expected: date):
    assert parse_statement_date_from_filename(name) == expected


@pytest.mark.parametrize("name", [
    "chase_checking.pdf",
    "statement.pdf",
    "",
    None,
    # Invalid date components — must not crash, must return None
    "stmt-13-99-2024.pdf",
    "2024-13.pdf",
])
def test_returns_none_when_unrecognized(name):
    assert parse_statement_date_from_filename(name) is None


def test_strips_path():
    assert parse_statement_date_from_filename("/tmp/sub/stmt-2024-03-15.pdf") == date(2024, 3, 15)


def test_full_date_wins_over_month_only():
    # YMD pattern is checked before YM, so "2024-03-15" doesn't get truncated
    # to "2024-03" and returned as 2024-03-31.
    assert parse_statement_date_from_filename("2024-03-15-statement.pdf") == date(2024, 3, 15)
