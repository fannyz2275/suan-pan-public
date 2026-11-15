from app.engine.cashflow import project_cashflow
from datetime import date


def test_12_month_projection_basic():
    result = project_cashflow(
        liquid_assets=30000,
        monthly_income=8000,
        monthly_expenses=5000,
        months=12,
    )
    assert len(result) == 12
    assert result[0]["balance"] == 33000   # 30000 + (8000-5000)
    assert result[11]["balance"] == 66000  # 30000 + 12*3000


def test_zero_surplus():
    result = project_cashflow(
        liquid_assets=10000,
        monthly_income=5000,
        monthly_expenses=5000,
        months=3,
    )
    assert all(r["balance"] == 10000 for r in result)


def test_rsu_vesting_added_to_balance():
    vesting_events = [{"date": "2026-05-01", "value": 10000}]
    result = project_cashflow(
        liquid_assets=10000,
        monthly_income=5000,
        monthly_expenses=5000,
        months=6,
        vesting_events=vesting_events,
        start_date=date(2026, 3, 1),
    )
    may_row = next(r for r in result if r["month"] == "2026-05")
    assert may_row["vesting_income"] == 10000
    assert may_row["balance"] == 10000 + 10000  # prior 10000 + vest 10000


def test_result_fields():
    result = project_cashflow(liquid_assets=5000, monthly_income=3000, monthly_expenses=2000, months=1)
    row = result[0]
    assert "month" in row
    assert "balance" in row
    assert "monthly_net" in row
    assert "vesting_income" in row
