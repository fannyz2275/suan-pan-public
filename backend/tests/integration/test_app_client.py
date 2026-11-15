import pytest


@pytest.mark.requires_supabase
def test_app_client_auth(app_client, test_user):
    _, token = test_user
    res = app_client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["email"].endswith("@example.com")
