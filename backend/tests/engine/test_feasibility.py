from app.engine.feasibility import score_goal_feasibility
from datetime import date, timedelta


def test_fully_achievable_goal():
    result = score_goal_feasibility(
        target_amount=12000,
        current_progress=0,
        monthly_surplus=1000,
        target_date=(date.today() + timedelta(days=365)).isoformat(),
    )
    assert result["feasibility_score"] == 100.0
    assert result["status"] == "on_track"
    assert result["months_to_goal"] == 12


def test_off_track_goal():
    result = score_goal_feasibility(
        target_amount=100000,
        current_progress=0,
        monthly_surplus=500,
        target_date=(date.today() + timedelta(days=365)).isoformat(),
    )
    assert result["feasibility_score"] < 50
    assert result["status"] == "off_track"


def test_already_achieved():
    result = score_goal_feasibility(
        target_amount=10000,
        current_progress=10000,
        monthly_surplus=1000,
        target_date=(date.today() + timedelta(days=30)).isoformat(),
    )
    assert result["feasibility_score"] == 100.0
    assert result["status"] == "on_track"
    assert result["months_to_goal"] == 0


def test_zero_surplus_returns_off_track():
    result = score_goal_feasibility(
        target_amount=5000,
        current_progress=0,
        monthly_surplus=0,
        target_date=(date.today() + timedelta(days=180)).isoformat(),
    )
    assert result["feasibility_score"] == 0.0
    assert result["status"] == "off_track"


def test_at_risk_goal():
    result = score_goal_feasibility(
        target_amount=10000,
        current_progress=0,
        monthly_surplus=600,
        target_date=(date.today() + timedelta(days=365)).isoformat(),
    )
    # Achievable ~ 600*12=7200 out of 10000 = 72% → at_risk
    assert result["status"] == "at_risk"
    assert 60 <= result["feasibility_score"] < 90
