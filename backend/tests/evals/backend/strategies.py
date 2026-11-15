"""Hypothesis strategies for Spec B invariant tests (§6.0).

Each invariant references a strategy by name; bodies live here so that an
engine signature change is updated in exactly one place.
"""
from __future__ import annotations

import string
from datetime import date

from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Attribution — strategy for transaction lists fed to compute_attribution.
# ---------------------------------------------------------------------------

ATTRIBUTION_TXN_TYPES = (
    "buy",
    "sell",
    "dividend",
    "interest",
    "fee",
    "transfer_in",
    "transfer_out",
    "split",
    "reinvest",
)


@st.composite
def attribution_transaction_strategy(draw):
    txn_type = draw(st.sampled_from(ATTRIBUTION_TXN_TYPES))
    amount = draw(
        st.floats(
            min_value=-100_000,
            max_value=100_000,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    return {
        "type": txn_type,
        "amount": round(amount, 2),
        "date": draw(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31))),
        "ticker": draw(
            st.one_of(
                st.none(),
                st.text(alphabet=string.ascii_uppercase, min_size=1, max_size=5),
            )
        ),
    }


attribution_transactions = st.lists(
    attribution_transaction_strategy(), min_size=0, max_size=20
)


# ---------------------------------------------------------------------------
# Period values — start/end values that bracket plausible portfolios.
# ---------------------------------------------------------------------------

period_value = st.floats(
    min_value=0.0,
    max_value=10_000_000.0,
    allow_nan=False,
    allow_infinity=False,
)
