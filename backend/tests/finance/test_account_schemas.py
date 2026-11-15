import pytest
from pydantic import ValidationError

from app.finance.schemas import AccountCreate


def test_account_create_accepts_nickname():
    a = AccountCreate(name="Chase Checking", type="checking", balance=100, nickname="Joint")
    assert a.nickname == "Joint"


def test_account_create_nickname_optional():
    a = AccountCreate(name="Chase Checking", type="checking", balance=100)
    assert a.nickname is None


def test_account_create_accepts_4_digit_last4():
    a = AccountCreate(
        name="Chase Checking", type="checking", balance=100,
        account_number_last4="1234",
    )
    assert a.account_number_last4 == "1234"


def test_account_create_rejects_short_last4():
    with pytest.raises(ValidationError):
        AccountCreate(
            name="Chase Checking", type="checking", balance=100,
            account_number_last4="12",
        )


def test_account_create_rejects_non_digit_last4():
    with pytest.raises(ValidationError):
        AccountCreate(
            name="Chase Checking", type="checking", balance=100,
            account_number_last4="abcd",
        )


def test_account_create_rejects_too_long_last4():
    with pytest.raises(ValidationError):
        AccountCreate(
            name="Chase Checking", type="checking", balance=100,
            account_number_last4="12345",
        )


def test_account_create_last4_optional():
    a = AccountCreate(name="Chase Checking", type="checking", balance=100)
    assert a.account_number_last4 is None
