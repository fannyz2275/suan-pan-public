"""Shared fixtures for portfolio tests."""
import pytest


@pytest.fixture(autouse=True)
def _disable_lazy_plaid_sync(monkeypatch):
    """The four read endpoints (holdings/exposure/timeseries/summary) call
    ensure_today_snapshot at the top, which on a real DB tries to call Plaid.
    In tests we patch it to a no-op so MagicMock chain auto-vivification
    doesn't accidentally exercise the lazy-sync path.

    Tests that explicitly want to exercise ensure_today_snapshot should
    override this fixture or invoke the real function.
    """
    monkeypatch.setattr(
        "app.portfolio.snapshots.ensure_today_snapshot",
        lambda *a, **kw: 0,
    )
