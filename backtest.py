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
    cagr: float                      # annualized return
    volatility: float                # annualized stdev of returns
    sharpe: float                    # CAGR / volatility (rf = 0 for v1)
    max_drawdown: float              # most negative peak-to-trough drop
    start: pd.Timestamp
    end: pd.Timestamp

    def summary(self) -> dict:
        return {
            "Start": self.start.date().isoformat(),
            "End": self.end.date().isoformat(),
            "Total Return": f"{self.total_return:.1%}",
            "CAGR": f"{self.cagr:.1%}",
            "Volatility": f"{self.volatility:.1%}",
            "Sharpe": f"{self.sharpe:.2f}",
            "Max Drawdown": f"{self.max_drawdown:.1%}",
        }


def run_backtest(
    prices: pd.DataFrame,
    allocation: Mapping[str, float],
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> BacktestResult:
    """Run a daily-rebalanced backtest of {ticker: weight} over [start, end]."""
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
    vol = port_rets.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = cagr / vol if vol > 0 else 0.0

    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    max_dd = drawdown.min()

    return BacktestResult(
        equity_curve=equity,
        daily_returns=port_rets,
        total_return=float(total_return),
        cagr=float(cagr),
        volatility=float(vol),
        sharpe=float(sharpe),
        max_drawdown=float(max_dd),
        start=equity.index[0],
        end=equity.index[-1],
    )


if __name__ == "__main__":
    from data import load_universe

    prices = load_universe()

    print("=== 60/40 SPY/AGG, all-time ===")
    result = run_backtest(prices, {"SPY": 0.6, "AGG": 0.4})
    for k, v in result.summary().items():
        print(f"  {k:15} {v}")

    print()
    print("=== 100% SPY, 2008 crash window ===")
    result = run_backtest(prices, {"SPY": 1.0}, start="2007-10-01", end="2009-06-30")
    for k, v in result.summary().items():
        print(f"  {k:15} {v}")

    print()
    print("=== Risk parity-ish (SPY/TLT/GLD), 2020-now ===")
    result = run_backtest(
        prices,
        {"SPY": 0.4, "TLT": 0.4, "GLD": 0.2},
        start="2020-01-01",
    )
    for k, v in result.summary().items():
        print(f"  {k:15} {v}")
