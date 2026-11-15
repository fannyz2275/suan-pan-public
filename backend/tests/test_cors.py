import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.parametrize('origin', [
    'http://localhost:5173', 'http://localhost:5174',
    'http://127.0.0.1:5173', 'http://127.0.0.1:5174',
])
def test_local_frontend_can_access_authenticated_api(origin):
    response = TestClient(app).options('/finance/accounts', headers={
        'Origin': origin, 'Access-Control-Request-Method': 'GET',
        'Access-Control-Request-Headers': 'authorization',
    })
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == origin


def test_unknown_origin_is_rejected():
    response = TestClient(app).options('/finance/accounts', headers={
        'Origin': 'https://untrusted.example', 'Access-Control-Request-Method': 'GET',
    })
    assert response.status_code == 400
    assert 'access-control-allow-origin' not in response.headers
