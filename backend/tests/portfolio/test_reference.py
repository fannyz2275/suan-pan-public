import pytest
from unittest.mock import MagicMock, patch

from app.portfolio.reference import country_to_region


@pytest.mark.parametrize("country,expected", [
    ("United States", "US"),
    ("Canada", "Developed"),
    ("Germany", "Developed"),
    ("Japan", "Developed"),
    ("China", "Emerging"),
    ("India", "Emerging"),
    ("Brazil", "Emerging"),
    (None, "Global"),
    ("", "Global"),
    ("Unknown Country", "Global"),
])
def test_country_to_region(country, expected):
    assert country_to_region(country) == expected


def test_enrich_ticker_individual_stock():
    from app.portfolio.reference import enrich_ticker
    fake_info = {
        "longName": "NVIDIA Corporation",
        "quoteType": "EQUITY",
        "sector": "Technology",
        "country": "United States",
    }
    with patch("app.portfolio.reference.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.info = fake_info
        mock_ticker.return_value.funds_data = None
        result = enrich_ticker("NVDA")

    assert result["ticker"] == "NVDA"
    assert result["name"] == "NVIDIA Corporation"
    assert result["security_type"] == "stock"
    assert result["asset_class"] == "equity"
    assert result["sector"] == "Technology"
    assert result["region"] == "US"
    assert result["look_through"] is None


def test_enrich_ticker_etf_with_top_holdings():
    from app.portfolio.reference import enrich_ticker
    fake_info = {
        "longName": "Vanguard S&P 500 ETF",
        "quoteType": "ETF",
        "country": "United States",
    }
    fake_top_holdings = MagicMock()
    fake_top_holdings.top_holdings = [
        {"symbol": "AAPL", "weight": 0.07},
        {"symbol": "MSFT", "weight": 0.06},
    ]
    with patch("app.portfolio.reference.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.info = fake_info
        mock_ticker.return_value.funds_data = fake_top_holdings
        result = enrich_ticker("VOO")

    assert result["security_type"] == "etf"
    assert result["asset_class"] == "equity"
    assert result["look_through"] == [
        {"ticker": "AAPL", "weight": 0.07},
        {"ticker": "MSFT", "weight": 0.06},
    ]


def test_enrich_ticker_unknown_falls_back():
    from app.portfolio.reference import enrich_ticker
    with patch("app.portfolio.reference.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.info = {}
        mock_ticker.return_value.funds_data = None
        result = enrich_ticker("ZZZZZ")

    assert result["ticker"] == "ZZZZZ"
    assert result["asset_class"] == "other"
    assert result["sector"] is None
    assert result["region"] == "Global"


def test_get_prices_returns_cached_when_complete():
    from datetime import date as _date
    from unittest.mock import MagicMock
    from app.portfolio.reference import get_prices

    db = MagicMock()
    db.table.return_value.select.return_value.in_.return_value.gte.return_value.lte.return_value.execute.return_value.data = [
        {"ticker": "NVDA", "date": "2026-04-01", "close": 900.0},
        {"ticker": "NVDA", "date": "2026-04-02", "close": 910.0},
    ]
    out = get_prices(db, ["NVDA"], _date(2026, 4, 1), _date(2026, 4, 2))
    assert out == {
        ("NVDA", _date(2026, 4, 1)): 900.0,
        ("NVDA", _date(2026, 4, 2)): 910.0,
    }
    # Should not call yfinance because cache covers window.
    # (we'd see the patch path used in the next test)


def test_get_prices_fetches_missing_via_yfinance_and_caches():
    from datetime import date as _date
    from unittest.mock import MagicMock, patch
    import pandas as pd
    from app.portfolio.reference import get_prices

    db = MagicMock()
    db.table.return_value.select.return_value.in_.return_value.gte.return_value.lte.return_value.execute.return_value.data = []
    db.table.return_value.upsert.return_value.execute.return_value.data = []

    fake_history = pd.DataFrame(
        {"Close": [900.0, 910.0]},
        index=pd.to_datetime(["2026-04-01", "2026-04-02"]),
    )
    with patch("app.portfolio.reference.yf.download", return_value=fake_history) as mock_dl:
        out = get_prices(db, ["NVDA"], _date(2026, 4, 1), _date(2026, 4, 2))
        mock_dl.assert_called_once()

    assert out[("NVDA", _date(2026, 4, 1))] == 900.0
    assert out[("NVDA", _date(2026, 4, 2))] == 910.0


def test_enrich_fund_reads_yahoo_holdings_dataframe():
    import pandas as pd
    from app.portfolio.reference import enrich_ticker

    funds = MagicMock()
    funds.top_holdings = pd.DataFrame(
        {"Name": ["Apple", "Microsoft"], "Holding Percent": [0.07, 0.06]},
        index=pd.Index(["AAPL", "MSFT"], name="Symbol"),
    )
    with patch("app.portfolio.reference.yf.Ticker") as ticker:
        ticker.return_value.info = {"quoteType": "ETF", "longName": "Example ETF"}
        ticker.return_value.funds_data = funds
        result = enrich_ticker("EXAMPLE")
    assert result["look_through"] == [
        {"ticker": "AAPL", "weight": 0.07},
        {"ticker": "MSFT", "weight": 0.06},
    ]
    assert result["enrichment_source"] == "yfinance"


def test_get_prices_handles_single_ticker_multiindex():
    from datetime import date
    import pandas as pd
    from app.portfolio.reference import get_prices

    db = MagicMock()
    db.table.return_value.select.return_value.in_.return_value.gte.return_value.lte.return_value.execute.return_value.data = []
    db.table.return_value.select.return_value.in_.return_value.gte.return_value.execute.return_value.data = []
    prices = pd.DataFrame(
        [[123.0]], index=pd.to_datetime(["2026-04-01"]),
        columns=pd.MultiIndex.from_tuples([("NVDA", "Close")]),
    )
    with patch("app.portfolio.reference.yf.download", return_value=prices):
        result = get_prices(db, ["NVDA"], date(2026, 4, 1), date(2026, 4, 1))
    assert result == {("NVDA", date(2026, 4, 1)): 123.0}


def test_backfill_uses_yahoo_without_provider_key(monkeypatch):
    from app.portfolio.reference import ensure_enriched

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    db = MagicMock()
    db.table.return_value.select.return_value.in_.return_value.execute.return_value.data = []
    with patch("app.portfolio.reference.yf.Ticker") as ticker:
        ticker.return_value.info = {"quoteType": "EQUITY", "country": "United States"}
        ticker.return_value.funds_data = None
        count = ensure_enriched(db, ["NVDA"])
    assert count == 1
    payload = db.table.return_value.upsert.call_args.args[0]
    assert payload[0]["country"] == "United States"
    assert payload[0]["enrichment_source"] == "yfinance"


def test_enrich_fund_preserves_metadata_when_holdings_unavailable():
    from unittest.mock import PropertyMock
    from app.portfolio.reference import enrich_ticker

    with patch("app.portfolio.reference.yf.Ticker") as ticker:
        ticker.return_value.info = {"quoteType": "ETF", "longName": "Example ETF"}
        type(ticker.return_value).funds_data = PropertyMock(side_effect=RuntimeError("unavailable"))
        result = enrich_ticker("EXAMPLE")
    assert result["name"] == "Example ETF"
    assert result["security_type"] == "etf"
    assert result["look_through"] is None


@pytest.mark.parametrize("age_days,expected", [(1, 0), (8, 1)])
def test_thin_metadata_backfill_respects_retry_ttl(monkeypatch, age_days, expected):
    from datetime import datetime, timedelta, timezone
    from app.portfolio.reference import ensure_enriched

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    db = MagicMock()
    db.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [{
        "ticker": "UNKNOWN", "country": None, "look_through": None,
        "enriched_at": (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat(),
    }]
    with patch("app.portfolio.reference.yf.Ticker") as ticker:
        ticker.return_value.info = {}
        ticker.return_value.funds_data = None
        assert ensure_enriched(db, ["UNKNOWN"]) == expected


def test_price_misses_skip_download_without_extending_ttl():
    from datetime import date
    from app.portfolio.reference import get_prices_with_misses

    db = MagicMock()
    db.table.return_value.select.return_value.in_.return_value.gte.return_value.lte.return_value.execute.return_value.data = []
    db.table.return_value.select.return_value.in_.return_value.gte.return_value.execute.return_value.data = [{"ticker": "UNKNOWN"}]
    with patch("app.portfolio.reference.yf.download") as download:
        assert get_prices_with_misses(db, ["UNKNOWN"], date(2026, 4, 1), date(2026, 4, 2)) == ({}, ["UNKNOWN"])
    download.assert_not_called()
    db.table.return_value.upsert.assert_not_called()
