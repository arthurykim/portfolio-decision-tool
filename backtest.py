"""Backtest engine: run a portfolio allocation against historical prices."""
from dataclasses import dataclass
from typing import Mapping
import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


@dataclass
class BacktestResult:
    equity_curve: pd.Series          # portfolio value over time, starts at 1.0
    daily_returns: pd.Series         # weighted daily returns
    total_return: float              # final / initial - 1
    cagr: float                      # annualized nominal return
    real_cagr: float                 # annualized return after inflation
    volatility: float                # annualized stdev of returns
    downside_volatility: float       # annualized stdev of losing days only
    sharpe: float                    # excess return per unit of total volatility
    sortino: float                   # excess return per unit of downside volatility
    calmar: float                    # CAGR per unit of max drawdown
    max_drawdown: float              # most negative peak-to-trough drop
    longest_drawdown_days: int       # longest stretch below a prior peak
    risk_free_rate: float            # annualized rate used for Sharpe/Sortino
    inflation_rate: float            # annualized inflation over the window
    start: pd.Timestamp              # first day of the equity curve
    end: pd.Timestamp
    price_start: pd.Timestamp        # first priced day (one before `start`, since
                                     # the first return needs a prior close)

    def summary(self) -> dict:
        return {
            "Start": self.start.date().isoformat(),
            "End": self.end.date().isoformat(),
            "Total Return": f"{self.total_return:.1%}",
            "CAGR": f"{self.cagr:.1%}",
            "Real CAGR": f"{self.real_cagr:.1%}",
            "Volatility": f"{self.volatility:.1%}",
            "Sharpe": f"{self.sharpe:.2f}",
            "Sortino": f"{self.sortino:.2f}",
            "Calmar": f"{self.calmar:.2f}",
            "Max Drawdown": f"{self.max_drawdown:.1%}",
            "Longest Recovery": f"{self.longest_drawdown_days} days",
        }


def longest_underwater_days(equity: pd.Series) -> int:
    """Longest stretch (calendar days) the curve spent below a previous peak."""
    underwater = equity < equity.cummax()
    longest, run_start = 0, None
    for date, is_under in underwater.items():
        if is_under and run_start is None:
            run_start = date
        elif not is_under and run_start is not None:
            longest = max(longest, (date - run_start).days)
            run_start = None
    if run_start is not None:  # still underwater at the end of the window
        longest = max(longest, (equity.index[-1] - run_start).days)
    return int(longest)


def run_backtest(
    prices: pd.DataFrame,
    allocation: Mapping[str, float],
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    risk_free_rate: float = 0.0,
    inflation_rate: float = 0.0,
) -> BacktestResult:
    """Run a daily-rebalanced backtest of {ticker: weight} over [start, end].

    `risk_free_rate` and `inflation_rate` are annualized decimals for the same
    window; the caller supplies them so this stays a pure function of its inputs.
    """
    weight_sum = sum(allocation.values())
    if not np.isclose(weight_sum, 1.0, atol=1e-3):
        raise ValueError(f"Allocation weights must sum to 1.0, got {weight_sum:.4f}")

    missing = [t for t in allocation if t not in prices.columns]
    if missing:
        raise ValueError(f"Tickers not in price data: {missing}")

    cols = list(allocation.keys())
    px = prices[cols].copy()
    if start is not None:
        px = px[px.index >= pd.Timestamp(start)]
    if end is not None:
        px = px[px.index <= pd.Timestamp(end)]
    px = px.dropna()  # drop dates where any ticker is missing

    if len(px) < 2:
        raise ValueError("Not enough overlapping price data for selected tickers/range")

    daily_rets = px.pct_change().dropna()
    weights = pd.Series(allocation)[cols]
    port_rets = daily_rets @ weights
    equity = (1 + port_rets).cumprod()

    total_return = equity.iloc[-1] - 1
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (equity.iloc[-1]) ** (1 / years) - 1 if years > 0 else 0.0
    real_cagr = (1 + cagr) / (1 + inflation_rate) - 1

    vol = port_rets.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    losses = port_rets[port_rets < 0]
    downside_vol = losses.std() * np.sqrt(TRADING_DAYS_PER_YEAR) if len(losses) > 1 else 0.0

    excess = cagr - risk_free_rate
    sharpe = excess / vol if vol > 0 else 0.0
    sortino = excess / downside_vol if downside_vol > 0 else 0.0

    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    max_dd = drawdown.min()
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0

    return BacktestResult(
        equity_curve=equity,
        daily_returns=port_rets,
        total_return=float(total_return),
        cagr=float(cagr),
        real_cagr=float(real_cagr),
        volatility=float(vol),
        downside_volatility=float(downside_vol),
        sharpe=float(sharpe),
        sortino=float(sortino),
        calmar=float(calmar),
        max_drawdown=float(max_dd),
        longest_drawdown_days=longest_underwater_days(equity),
        risk_free_rate=float(risk_free_rate),
        inflation_rate=float(inflation_rate),
        start=equity.index[0],
        end=equity.index[-1],
        price_start=px.index[0],
    )


if __name__ == "__main__":
    from data import annualized_inflation, load_universe, risk_free_rate as rf

    prices = load_universe()

    for label, alloc, window in [
        ("60/40 SPY/AGG, all-time", {"SPY": 0.6, "AGG": 0.4}, (None, None)),
        ("100% SPY, 2008 crash", {"SPY": 1.0}, ("2007-10-01", "2009-06-30")),
        ("SPY/TLT/GLD, 2020-now", {"SPY": 0.4, "TLT": 0.4, "GLD": 0.2}, ("2020-01-01", None)),
    ]:
        print(f"=== {label} ===")
        result = run_backtest(
            prices, alloc, start=window[0], end=window[1],
            risk_free_rate=rf(prices, *window),
            inflation_rate=annualized_inflation(*window)[0],
        )
        for k, v in result.summary().items():
            print(f"  {k:18} {v}")
        print()
