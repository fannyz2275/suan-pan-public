from app.portfolio.exposure import compute_exposure


def _ref(ticker, asset_class="equity", sector=None, region="US", look_through=None):
    return {
        "ticker": ticker, "asset_class": asset_class,
        "sector": sector, "region": region, "look_through": look_through,
    }


def test_asset_class_no_look_through():
    holdings = [
        {"ticker": "NVDA", "market_value": 10000},
        {"ticker": "BND", "market_value": 5000},
    ]
    refs = {
        "NVDA": _ref("NVDA", asset_class="equity", sector="Technology"),
        "BND": _ref("BND", asset_class="fixed_income"),
    }
    out = compute_exposure(holdings, refs, dimension="asset_class")
    by_label = {s["label"]: s for s in out}
    assert by_label["equity"]["market_value"] == 10000
    assert by_label["fixed_income"]["market_value"] == 5000
    assert abs(by_label["equity"]["percent"] - 10000 / 15000 * 100) < 0.001


def test_sector_with_etf_look_through():
    holdings = [
        {"ticker": "VOO", "market_value": 10000},
    ]
    refs = {
        "VOO": _ref(
            "VOO", asset_class="equity", sector=None, region="US",
            look_through=[
                {"ticker": "AAPL", "weight": 0.07},
                {"ticker": "MSFT", "weight": 0.06},
            ],
        ),
        "AAPL": _ref("AAPL", asset_class="equity", sector="Technology"),
        "MSFT": _ref("MSFT", asset_class="equity", sector="Technology"),
    }
    out = compute_exposure(holdings, refs, dimension="sector")
    by_label = {s["label"]: s for s in out}
    # 13% goes to Technology (AAPL+MSFT), 87% residual goes to "Other"
    # because VOO itself has no sector.
    assert abs(by_label["Technology"]["market_value"] - 10000 * 0.13) < 0.01
    assert abs(by_label["Other"]["market_value"] - 10000 * 0.87) < 0.01


def test_asset_class_does_not_use_look_through():
    holdings = [{"ticker": "VOO", "market_value": 10000}]
    refs = {
        "VOO": _ref("VOO", asset_class="equity",
                    look_through=[{"ticker": "AAPL", "weight": 0.07}]),
        "AAPL": _ref("AAPL", asset_class="equity"),
    }
    out = compute_exposure(holdings, refs, dimension="asset_class")
    assert len(out) == 1
    assert out[0]["label"] == "equity"
    assert out[0]["market_value"] == 10000


def test_unknown_ticker_falls_back_to_other():
    holdings = [{"ticker": "ZZZZ", "market_value": 5000}]
    refs: dict = {}
    out = compute_exposure(holdings, refs, dimension="sector")
    assert out == [{"label": "Other", "market_value": 5000, "percent": 100.0}]


def test_results_sorted_descending():
    holdings = [
        {"ticker": "A", "market_value": 100},
        {"ticker": "B", "market_value": 500},
        {"ticker": "C", "market_value": 250},
    ]
    refs = {
        "A": _ref("A", sector="Tech"),
        "B": _ref("B", sector="Health"),
        "C": _ref("C", sector="Energy"),
    }
    out = compute_exposure(holdings, refs, dimension="sector")
    labels = [s["label"] for s in out]
    assert labels == ["Health", "Energy", "Tech"]
