"""Unit tests for app.policy.intent — the 5-class regex classifier.

Coarse by design; these tests pin the keyword-to-label mapping so future
edits are intentional."""
from __future__ import annotations

import pytest

from app.policy.intent import OTHER, classify


@pytest.mark.parametrize("text", [
    "should I refinance my mortgage?",
    "what if I save $500/mo more",
    "simulate buying a $35k car",
    "project my cashflow for the next year",
    "can I afford to retire at 50?",
    "run a monte carlo for me",
    "should I prepay my loan?",
    "will I have enough?",
])
def test_advice_signals_classified_first(text):
    """advice questions take priority over goal/spending keywords that may
    co-occur ('should I save more for retirement?' is advice, not goal)."""
    assert classify(text) == "asking_about_advice"


@pytest.mark.parametrize("text", [
    "am I on track for the house goal?",
    "what's my emergency fund target?",
    "how feasible is my retirement goal?",
    "saving for a down payment",
])
def test_goals_signals(text):
    assert classify(text) == "asking_about_goals"


@pytest.mark.parametrize("text", [
    "review my transfers",
    "is the venmo cashout external?",
    "show transfers between my accounts",
    "mark this as external please",
    "those zelle payments aren't real expenses",
])
def test_transfers_signals(text):
    assert classify(text) == "asking_about_transfers"


@pytest.mark.parametrize("text", [
    "how much did I spend last month?",
    "compare my january spending vs february",
    "where did my money go in q1?",
    "break down my expenses by category",
    "what's my budget for food?",
])
def test_spending_signals(text):
    assert classify(text) == "asking_about_spending"


@pytest.mark.parametrize("text", [
    "hello",
    "thanks",
    "tell me a joke",
    "what tools do you have?",
])
def test_other_fallback(text):
    assert classify(text) == OTHER


def test_empty_input_returns_other():
    assert classify("") == OTHER
    assert classify(None) == OTHER
