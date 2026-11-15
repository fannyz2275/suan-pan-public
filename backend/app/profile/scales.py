"""Anchor sentences for the 1-5 identity scalars.

Single source of truth used by:
  • advisor.context — to render "Risk 3/5 (balanced)" in the T1 one-liner so
    the LLM gets both number and meaning.
  • profile.router — exposed via GET /profile/scales for the ProfileCard
    sliders (PR-C) to show identical tooltip copy on each notch.

Risk anchors paraphrase a "loss tolerance vs. upside ambition" spectrum,
not a generic conservative/moderate/aggressive label — those are too
vague to anchor a real conversation. Horizon anchors map to concrete
year ranges so the user picks a notch by life-event distance, not by
adjective.
"""
from __future__ import annotations

from typing import Literal, TypedDict


class Anchor(TypedDict):
    value: int
    label: str  # short label (used inline in the prompt and on the slider)
    description: str  # full sentence shown in tooltips


RiskValue = Literal[1, 2, 3, 4, 5]
HorizonValue = Literal[1, 2, 3, 4, 5]


RISK_ANCHORS: dict[int, Anchor] = {
    1: {
        "value": 1,
        "label": "capital preservation",
        "description": (
            "Nominal balance must never decrease. Willing to accept very "
            "low real returns to keep the dollar number stable."
        ),
    },
    2: {
        "value": 2,
        "label": "cautious",
        "description": (
            "Mild drawdowns are acceptable for modest growth. Would still "
            "be uncomfortable through a 10% portfolio decline."
        ),
    },
    3: {
        "value": 3,
        "label": "balanced",
        "description": (
            "Stoic during a 15% market drawdown if it facilitates "
            "long-term wealth accumulation."
        ),
    },
    4: {
        "value": 4,
        "label": "growth-oriented",
        "description": (
            "Comfortable holding through a 30% drawdown. Willing to take "
            "concentrated equity bets for above-market returns."
        ),
    },
    5: {
        "value": 5,
        "label": "high conviction",
        "description": (
            "Able to handle the total loss of specific moonshot positions "
            "in pursuit of 10× returns."
        ),
    },
}

HORIZON_ANCHORS: dict[int, Anchor] = {
    1: {
        "value": 1,
        "label": "<1 year",
        "description": "Money is needed within the next 12 months.",
    },
    2: {
        "value": 2,
        "label": "~2 years",
        "description": "Goal is roughly 1 to 3 years out.",
    },
    3: {
        "value": 3,
        "label": "~3 years",
        "description": "Goal is roughly 3 years out.",
    },
    4: {
        "value": 4,
        "label": "~5 years",
        "description": "Goal is 4 to 6 years out.",
    },
    5: {
        "value": 5,
        "label": ">6 years",
        "description": "Money is not needed for at least 6 years.",
    },
}


def render_risk(value: int | None) -> str | None:
    """`'Risk 3/5 (balanced)'` for valid input; None when value is missing."""
    if value is None:
        return None
    anchor = RISK_ANCHORS.get(int(value))
    if anchor is None:
        return None
    return f"Risk {anchor['value']}/5 ({anchor['label']})"


def render_horizon(value: int | None) -> str | None:
    """`'Horizon 4/5 (~5 years)'` for valid input; None when value is missing."""
    if value is None:
        return None
    anchor = HORIZON_ANCHORS.get(int(value))
    if anchor is None:
        return None
    return f"Horizon {anchor['value']}/5 ({anchor['label']})"


def all_scales() -> dict[str, list[Anchor]]:
    """Payload for GET /profile/scales — used by the frontend slider tooltips
    so backend prompt copy and UI copy never drift apart.
    """
    return {
        "risk_tolerance": [RISK_ANCHORS[k] for k in sorted(RISK_ANCHORS)],
        "time_horizon": [HORIZON_ANCHORS[k] for k in sorted(HORIZON_ANCHORS)],
    }
