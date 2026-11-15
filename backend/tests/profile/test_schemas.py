import pytest
from pydantic import ValidationError
from app.profile.schemas import ProfileUpdate


def test_accepts_all_optional():
    m = ProfileUpdate()
    assert m.model_dump(exclude_none=True) == {}


def test_accepts_full_payload():
    m = ProfileUpdate(
        age=32,
        risk_tolerance="moderate",
        risk_tolerance_v2=3,
        time_horizon="medium",
        time_horizon_v2=3,
        employment_status="employed",
        region="SF Bay Area",
        dependents=2,
    )
    assert m.age == 32
    assert m.risk_tolerance == "moderate"
    assert m.risk_tolerance_v2 == 3
    assert m.time_horizon_v2 == 3
    assert m.employment_status == "employed"
    assert m.region == "SF Bay Area"


def test_rejects_invalid_risk_tolerance():
    with pytest.raises(ValidationError):
        ProfileUpdate(risk_tolerance="yolo")


def test_rejects_risk_tolerance_v2_out_of_range():
    """1-5 scalar must be inside the closed range."""
    with pytest.raises(ValidationError):
        ProfileUpdate(risk_tolerance_v2=0)
    with pytest.raises(ValidationError):
        ProfileUpdate(risk_tolerance_v2=6)


def test_rejects_time_horizon_v2_out_of_range():
    with pytest.raises(ValidationError):
        ProfileUpdate(time_horizon_v2=0)
    with pytest.raises(ValidationError):
        ProfileUpdate(time_horizon_v2=99)


def test_rejects_invalid_employment_status():
    with pytest.raises(ValidationError):
        ProfileUpdate(employment_status="freelance")  # not in the enum


def test_rejects_age_out_of_range():
    with pytest.raises(ValidationError):
        ProfileUpdate(age=200)


def test_rejects_negative_dependents():
    with pytest.raises(ValidationError):
        ProfileUpdate(dependents=-1)
