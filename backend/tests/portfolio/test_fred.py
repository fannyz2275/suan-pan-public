from datetime import date
from unittest.mock import MagicMock, patch


def test_fetch_fred_series_parses_csv():
    from app.portfolio.fred import fetch_fred_series, _CACHE
    _CACHE.clear()

    fake_csv = (
        "DATE,DGS10\n"
        "2026-04-01,4.20\n"
        "2026-04-02,4.18\n"
        "2026-04-03,.\n"   # FRED uses "." for missing
        "2026-04-04,4.15\n"
    )
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.text = fake_csv

    with patch("app.portfolio.fred.httpx.get", return_value=fake_resp):
        out = fetch_fred_series("DGS10", date(2026, 4, 1), date(2026, 4, 4))

    assert out == {
        date(2026, 4, 1): 4.20,
        date(2026, 4, 2): 4.18,
        date(2026, 4, 4): 4.15,
    }


def test_fetch_fred_series_returns_empty_on_http_error():
    from app.portfolio.fred import fetch_fred_series, _CACHE
    _CACHE.clear()

    fake_resp = MagicMock()
    fake_resp.status_code = 500
    with patch("app.portfolio.fred.httpx.get", return_value=fake_resp):
        out = fetch_fred_series("DGS10", date(2026, 4, 1), date(2026, 4, 4))
    assert out == {}


def test_fetch_fred_series_caches_within_process():
    """Two calls in the same process for the same (series, range) only fetch once."""
    from app.portfolio.fred import fetch_fred_series, _CACHE
    _CACHE.clear()

    fake_csv = "DATE,DGS10\n2026-04-01,4.20\n"
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.text = fake_csv

    with patch("app.portfolio.fred.httpx.get", return_value=fake_resp) as mock_get:
        fetch_fred_series("DGS10", date(2026, 4, 1), date(2026, 4, 1))
        fetch_fred_series("DGS10", date(2026, 4, 1), date(2026, 4, 1))

    assert mock_get.call_count == 1
