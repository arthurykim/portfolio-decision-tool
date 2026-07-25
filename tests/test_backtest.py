"""Unit tests for the backtest engine using synthetic price data."""
import numpy as np
import pandas as pd
import pytest

from backtest import longest_underwater_days, run_backtest


@pytest.fixture
def prices():
    """Three years of synthetic daily prices.

    UP/FLAT/DOWN are monotonic so return maths is exactly predictable; NOISY has
    real up and down days, which is what the downside/drawdown metrics need.
    """
    dates = pd.bdate_range("2020-01-01", periods=756)
    up = 100 * (1.0004 ** np.arange(756))       # ~10%/yr steady riser
    flat = np.full(756, 100.0)
    down = 100 * (0.9998 ** np.arange(756))
    # Seed 4 is fixed deliberately: it drifts up (+86%) while still taking a real
    # -22% drawdown, which is what the downside metrics need to be meaningful.
    rng = np.random.default_rng(4)
    noisy = 100 * np.exp(np.cumsum(rng.normal(0.0008, 0.009, 756)))
    return pd.DataFrame(
        {"UP": up, "FLAT": flat, "DOWN": down, "NOISY": noisy}, index=dates
    )


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


def test_risk_free_rate_lowers_sharpe(prices):
    base = run_backtest(prices, {"UP": 0.5, "DOWN": 0.5})
    with_rf = run_backtest(prices, {"UP": 0.5, "DOWN": 0.5}, risk_free_rate=0.04)
    assert with_rf.sharpe < base.sharpe
    assert with_rf.risk_free_rate == 0.04


def test_inflation_lowers_real_cagr(prices):
    r = run_backtest(prices, {"UP": 1.0}, inflation_rate=0.03)
    assert r.real_cagr < r.cagr
    assert r.real_cagr == pytest.approx((1 + r.cagr) / 1.03 - 1, rel=1e-9)


def test_real_cagr_equals_nominal_without_inflation(prices):
    r = run_backtest(prices, {"UP": 1.0})
    assert r.real_cagr == pytest.approx(r.cagr, rel=1e-9)


def test_sortino_exceeds_sharpe_for_an_upward_drifting_asset(prices):
    # Downside deviation ignores winning days, so it is smaller than total
    # volatility whenever the asset drifts up — making Sortino the larger ratio.
    r = run_backtest(prices, {"NOISY": 1.0})
    assert r.downside_volatility < r.volatility
    assert r.sortino > r.sharpe > 0


def test_calmar_is_cagr_over_drawdown(prices):
    r = run_backtest(prices, {"NOISY": 1.0})
    assert r.max_drawdown < 0
    assert r.calmar == pytest.approx(r.cagr / abs(r.max_drawdown), rel=1e-9)


def test_no_downside_days_yields_zero_sortino(prices):
    # A perfectly monotonic riser has no losing days at all; guard the 0/0 case.
    r = run_backtest(prices, {"UP": 1.0})
    assert r.downside_volatility == 0.0
    assert r.sortino == 0.0


def test_flat_portfolio_has_no_underwater_period(prices):
    assert run_backtest(prices, {"FLAT": 1.0}).longest_drawdown_days == 0


def test_monotonic_decline_is_underwater_almost_throughout(prices):
    r = run_backtest(prices, {"DOWN": 1.0})
    span = (r.end - r.start).days
    assert r.longest_drawdown_days >= span - 5


def test_longest_underwater_measures_the_longest_run():
    dates = pd.bdate_range("2020-01-01", periods=9)
    # peak, dip for 3 days, recover, dip for 5 days, still down at the end
    equity = pd.Series([1.0, 0.9, 0.9, 0.9, 1.1, 1.0, 0.95, 0.9, 0.85], index=dates)
    assert longest_underwater_days(equity) == (dates[8] - dates[5]).days
