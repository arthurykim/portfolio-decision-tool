"""Unit tests for the backtest engine using synthetic price data."""
import numpy as np
import pandas as pd
import pytest

from backtest import run_backtest


@pytest.fixture
def prices():
    """Three years of synthetic daily prices: one riser, one flat, one faller."""
    dates = pd.bdate_range("2020-01-01", periods=756)
    up = 100 * (1.0004 ** np.arange(756))       # ~10%/yr steady riser
    flat = np.full(756, 100.0)
    down = 100 * (0.9998 ** np.arange(756))
    return pd.DataFrame({"UP": up, "FLAT": flat, "DOWN": down}, index=dates)


def test_flat_portfolio_has_zero_return(prices):
    r = run_backtest(prices, {"FLAT": 1.0})
    assert r.total_return == pytest.approx(0.0, abs=1e-9)
    assert r.max_drawdown == pytest.approx(0.0, abs=1e-9)
    assert r.volatility == pytest.approx(0.0, abs=1e-9)


def test_single_asset_matches_price_ratio(prices):
    r = run_backtest(prices, {"UP": 1.0})
    expected = prices["UP"].iloc[-1] / prices["UP"].iloc[0] - 1
    assert r.total_return == pytest.approx(expected, rel=1e-6)


def test_blend_is_between_components(prices):
    up = run_backtest(prices, {"UP": 1.0}).total_return
    down = run_backtest(prices, {"DOWN": 1.0}).total_return
    blend = run_backtest(prices, {"UP": 0.5, "DOWN": 0.5}).total_return
    assert down < blend < up


def test_declining_asset_has_negative_drawdown(prices):
    r = run_backtest(prices, {"DOWN": 1.0})
    assert r.max_drawdown < -0.10
    # Monotone fall: drawdown ~= total return (equity starts one day after prices)
    assert r.max_drawdown == pytest.approx(r.total_return, rel=5e-3)


def test_weights_must_sum_to_one(prices):
    with pytest.raises(ValueError, match="sum to 1.0"):
        run_backtest(prices, {"UP": 0.5})


def test_unknown_ticker_rejected(prices):
    with pytest.raises(ValueError, match="not in price data"):
        run_backtest(prices, {"NOPE": 1.0})


def test_date_range_slicing(prices):
    r = run_backtest(prices, {"UP": 1.0}, start="2021-01-01", end="2021-12-31")
    assert r.start >= pd.Timestamp("2021-01-01")
    assert r.end <= pd.Timestamp("2021-12-31")


def test_empty_range_raises(prices):
    with pytest.raises(ValueError, match="Not enough"):
        run_backtest(prices, {"UP": 1.0}, start="2030-01-01")
