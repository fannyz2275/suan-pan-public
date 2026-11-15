from app.engine.monte_carlo import run_monte_carlo


def test_returns_probability_distribution():
    result = run_monte_carlo(
        initial_portfolio=100000,
        monthly_contribution=1000,
        years=30,
        simulations=1000,
    )
    assert "p10" in result
    assert "p25" in result
    assert "p50" in result
    assert "p75" in result
    assert "p90" in result
    assert "years" in result
    assert "simulations" in result
    assert result["p50"] > 100000
    assert result["p10"] < result["p50"] < result["p90"]


def test_success_rate_with_target():
    result = run_monte_carlo(
        initial_portfolio=500000,
        monthly_contribution=2000,
        years=10,
        simulations=1000,
        target_amount=1_000_000,
    )
    assert "success_rate" in result
    assert 0.0 <= result["success_rate"] <= 1.0


def test_no_target_no_success_rate():
    result = run_monte_carlo(
        initial_portfolio=100000,
        monthly_contribution=500,
        years=10,
        simulations=500,
    )
    assert "success_rate" not in result


def test_deterministic_with_seed():
    r1 = run_monte_carlo(initial_portfolio=50000, monthly_contribution=500, years=20, simulations=500)
    r2 = run_monte_carlo(initial_portfolio=50000, monthly_contribution=500, years=20, simulations=500)
    assert r1["p50"] == r2["p50"]
