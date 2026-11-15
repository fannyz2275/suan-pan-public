import pytest

from app.engine.recurring.normalize import normalize_description, token_set, jaccard


def test_normalize_strips_pos_debit_and_digits():
    assert normalize_description("POS DEBIT GREYSTAR APTS #5521 04/01/26") == "greystar apts"


def test_normalize_strips_ach_and_confirmation_codes():
    assert normalize_description("ACH TRANSFER NETFLIX INC 8827391") == "netflix inc"


def test_normalize_keeps_up_to_three_tokens():
    assert normalize_description("AMAZON WEB SERVICES USAGE CHARGE") == "amazon web services"


def test_normalize_empty_returns_empty_string():
    assert normalize_description("") == ""
    assert normalize_description("ACH DEBIT 123") == ""


def test_token_set_is_lowercase_unique():
    assert token_set("Greystar Apts Rent") == {"greystar", "apts", "rent"}


def test_jaccard_identical_is_one():
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0


def test_jaccard_disjoint_is_zero():
    assert jaccard({"a"}, {"b"}) == 0.0


def test_jaccard_partial_overlap():
    assert jaccard({"a", "b"}, {"a", "c"}) == pytest.approx(1 / 3)


def test_jaccard_empty_sets_is_zero():
    assert jaccard(set(), set()) == 0.0
