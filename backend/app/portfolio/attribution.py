from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def compute_attribution(
    *,
    start_value: float,
    end_value: float,
    transactions: Iterable[dict],
    clean_market_estimate: Optional[float] = None,
) -> Dict[str, Any]:
    """Decompose end_value − start_value into named buckets.

    Identity: end - start = contributions + withdrawals + dividends + trades + market + unattributed

    Buckets:
    - contributions: sum of transfer_in amounts (positive cash in)
    - withdrawals: sum of transfer_out amounts (signed; negative for cash out)
    - dividends: sum of dividend + interest amounts. reinvest contributes 0.
    - trades: realized P&L from buy/sell pairs when cost_basis_at_sell is provided
              on every sell row. Otherwise falls back to net cash impact of buy/sell
              rows and trades_has_basis=False.
    - market: when clean_market_estimate is provided (e.g. a benchmark-derived figure),
              market = clean_market_estimate and the residual goes to unattributed.
              Otherwise, market absorbs the residual and unattributed = 0.

    The output is a flat dict; the router maps it to the AttributionResult schema.
    """
    contributions = 0.0
    withdrawals = 0.0
    dividends = 0.0
    sells: List[dict] = []  # list of dict for trades calc
    buys: List[dict] = []
    has_basis = True

    for t in transactions:
        kind = t.get("type")
        amount = float(t.get("amount") or 0)
        if kind == "transfer_in":
            contributions += amount
        elif kind == "transfer_out":
            withdrawals += amount  # already signed negative
        elif kind in ("dividend", "interest"):
            dividends += amount
        elif kind == "reinvest":
            pass  # 0 net cash by convention
        elif kind == "fee":
            withdrawals += amount  # treat fees as a small negative flow
        elif kind == "buy":
            buys.append(t)
        elif kind == "sell":
            sells.append(t)
            if t.get("cost_basis_at_sell") is None:
                has_basis = False
        # split: ignore for cash-impact attribution; reflected in the next snapshot's qty.

    if buys or sells:
        if has_basis and sells:
            realized = 0.0
            for s in sells:
                cb = float(s.get("cost_basis_at_sell") or 0)
                proceeds = float(s.get("amount") or 0)  # positive cash in
                realized += proceeds - cb
            trades = realized
        else:
            # Fallback: net cash impact of all buy/sell rows in the period.
            trades = sum(float(t.get("amount") or 0) for t in buys + sells)
            has_basis = False
    else:
        trades = 0.0

    raw_change = end_value - start_value
    explained_ex_market = contributions + withdrawals + dividends + trades

    if clean_market_estimate is not None:
        market = float(clean_market_estimate)
        unattributed = raw_change - explained_ex_market - market
    else:
        market = raw_change - explained_ex_market
        unattributed = 0.0

    return {
        "start_value": float(start_value),
        "end_value": float(end_value),
        "contributions": round(contributions, 2),
        "withdrawals": round(withdrawals, 2),
        "dividends": round(dividends, 2),
        "trades": round(trades, 2),
        "trades_has_basis": has_basis,
        "market": round(market, 2),
        "unattributed": round(unattributed, 2),
    }
