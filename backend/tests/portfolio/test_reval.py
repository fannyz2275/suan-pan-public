from datetime import date

from app.portfolio.reval import revalue_at


def test_revalue_at_uses_exact_date_price():
    holdings = [
        {"ticker": "NVDA", "quantity": 10},
        {"ticker": "AAPL", "quantity": 20},
    ]
    prices = {
        ("NVDA", date(2026, 4, 1)): 950.0,
        ("AAPL", date(2026, 4, 1)): 180.0,
    }
    total = revalue_at(holdings, date(2026, 4, 1), prices, cash=500)
    assert total == 10 * 950 + 20 * 180 + 500


def test_revalue_at_carries_forward_missing_price():
    holdings = [{"ticker": "NVDA", "quantity": 10}]
    prices = {
        ("NVDA", date(2026, 3, 30)): 900.0,
        # no entry for 2026-04-01
    }
    total = revalue_at(holdings, date(2026, 4, 1), prices, cash=0)
    assert total == 10 * 900


def test_revalue_at_drops_holding_when_no_prior_price():
    holdings = [{"ticker": "NVDA", "quantity": 10}]
    prices: dict = {}
    total = revalue_at(holdings, date(2026, 4, 1), prices, cash=100)
    # NVDA has no price ever → contributes 0; cash still counts
    assert total == 100


def test_revalue_at_max_staleness():
    holdings = [{"ticker": "NVDA", "quantity": 10}]
    prices = {("NVDA", date(2026, 1, 1)): 900.0}
    # 90+ days stale → drop the holding
    total = revalue_at(holdings, date(2026, 5, 1), prices, cash=0, max_staleness_days=7)
    assert total == 0


def test_timeseries_uses_latest_snapshot_as_of_each_day():
    from app.portfolio.reval import timeseries
    snapshots = [
        {
            "snapshot_date": date(2026, 4, 1),
            "cash_value": 0,
            "holdings": [{"ticker": "NVDA", "quantity": 10}],
        },
        {
            "snapshot_date": date(2026, 4, 15),
            "cash_value": 0,
            "holdings": [{"ticker": "NVDA", "quantity": 12}],
        },
    ]
    prices = {
        ("NVDA", date(2026, 4, 1)): 900.0,
        ("NVDA", date(2026, 4, 10)): 950.0,
        ("NVDA", date(2026, 4, 15)): 1000.0,
    }
    series = timeseries(snapshots, prices, date(2026, 4, 1), date(2026, 4, 15))
    by_date = {p["date"]: p["total_value"] for p in series}
    assert by_date[date(2026, 4, 1)] == 10 * 900   # uses Apr 1 snapshot
    assert by_date[date(2026, 4, 10)] == 10 * 950  # still Apr 1 holdings, Apr 10 price
    assert by_date[date(2026, 4, 15)] == 12 * 1000 # uses Apr 15 snapshot


def test_timeseries_anchors_on_prior_snapshot_when_window_starts_mid_period():
    from app.portfolio.reval import timeseries
    snapshots = [
        {
            "snapshot_date": date(2026, 3, 1),
            "cash_value": 0,
            "holdings": [{"ticker": "AAPL", "quantity": 5}],
        },
    ]
    prices = {("AAPL", date(2026, 4, 1)): 200.0}
    series = timeseries(snapshots, prices, date(2026, 4, 1), date(2026, 4, 1))
    assert len(series) == 1
    assert series[0]["total_value"] == 5 * 200


def test_timeseries_returns_empty_when_no_prior_snapshot():
    from app.portfolio.reval import timeseries
    snapshots = [
        {
            "snapshot_date": date(2026, 5, 1),
            "cash_value": 0,
            "holdings": [{"ticker": "AAPL", "quantity": 5}],
        },
    ]
    series = timeseries(snapshots, {}, date(2026, 4, 1), date(2026, 4, 5))
    assert series == []
