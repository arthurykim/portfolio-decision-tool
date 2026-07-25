# How the Portfolio Decision Tool works

## What the tool does

The Portfolio Decision Tool backtests capital allocations against real historical daily
price data for ten supported ETFs. You pick weights (which must sum to 100%), an
optional date range, and the engine computes the portfolio's equity curve, CAGR,
volatility, Sharpe ratio, and max drawdown.

## Data source and freshness

Price history comes from Yahoo Finance (adjusted daily closes, which include dividends
via adjustment). History is cached locally and refreshed roughly once a day. Live
quotes shown in the quote strip are delayed about 15 minutes and are for display only.

## Methodology and assumptions

The backtest assumes continuous (daily) rebalancing to target weights, no trading
costs, no taxes, no slippage, and a risk-free rate of 0 for the Sharpe ratio. Dividends
are reflected through adjusted prices. The backtest window is automatically clipped to
the period where all selected tickers have overlapping data — for example VXUS data
begins in 2011, so any allocation including VXUS cannot be backtested before then.

## Limitations

Past performance does not predict future returns. Backtests are vulnerable to
survivorship of the chosen window, and the tool covers only ten US-listed ETFs — no
individual stocks, crypto, or non-US-listed funds. Results ignore taxes and trading
frictions, which favor high-turnover strategies. This tool is educational and does not
provide personalized investment advice; consult a licensed financial advisor for
decisions about your own money.

## The chat assistant

The chat assistant answers questions about finance concepts, the supported asset
classes, classic allocation strategies, and how this tool computes its numbers. It
retrieves passages from a curated knowledge base and answers based on them. It does not
give personalized investment advice or predictions.
