import numpy as np
from typing import Dict, Any, Optional


def run_monte_carlo(
    initial_portfolio: float,
    monthly_contribution: float,
    years: int,
    simulations: int = 5000,
    annual_return_mean: float = 0.07,
    annual_return_std: float = 0.15,
    inflation_rate: float = 0.03,
    target_amount: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Runs Monte Carlo simulation for portfolio growth.
    Returns percentile outcomes and optional success rate vs. target.
    Uses fixed seed for deterministic results.
    """
    months = years * 12
    monthly_mean = annual_return_mean / 12
    monthly_std = annual_return_std / (12 ** 0.5)

    rng = np.random.default_rng(seed=129)
    monthly_returns = rng.normal(monthly_mean, monthly_std, (simulations, months))

    portfolio = np.full(simulations, float(initial_portfolio))
    for m in range(months):
        portfolio = portfolio * (1 + monthly_returns[:, m]) + monthly_contribution

    # Adjust for inflation
    real_portfolio = portfolio / ((1 + inflation_rate) ** years)

    result: Dict[str, Any] = {
        "p10": round(float(np.percentile(real_portfolio, 10)), 2),
        "p25": round(float(np.percentile(real_portfolio, 25)), 2),
        "p50": round(float(np.percentile(real_portfolio, 50)), 2),
        "p75": round(float(np.percentile(real_portfolio, 75)), 2),
        "p90": round(float(np.percentile(real_portfolio, 90)), 2),
        "years": years,
        "simulations": simulations,
    }

    if target_amount is not None:
        result["success_rate"] = round(float(np.mean(real_portfolio >= target_amount)), 4)

    return result
