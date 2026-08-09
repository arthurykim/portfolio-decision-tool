# Performance metrics

## CAGR (Compound Annual Growth Rate)

CAGR is the annualized rate of return that would take a portfolio from its starting
value to its ending value if it grew at a constant rate every year. It is computed as
(ending value / starting value) ^ (1 / years) - 1. CAGR smooths out volatility, so two
portfolios with the same CAGR can have very different risk profiles. Historically, broad
US equity indexes have delivered a long-run CAGR of roughly 7-10% nominal, while
aggregate bonds have delivered roughly 3-5%.

## Total return

Total return is the simple percentage change in portfolio value over the full period:
ending value / starting value - 1. Unlike CAGR it is not annualized, so a 100% total
return over 20 years is far less impressive than 100% over 5 years.

## Volatility (annualized standard deviation)

Volatility measures how much daily returns fluctuate around their average, scaled to an
annual figure by multiplying the daily standard deviation by the square root of 252 (the
number of trading days in a year). Higher volatility means larger swings in portfolio
value. Equity indexes typically show 15-20% annualized volatility; aggregate bonds are
usually in the 4-6% range; portfolios mixing the two land in between.

## Sharpe ratio

The Sharpe ratio is return per unit of risk: (portfolio return - risk-free rate) /
volatility. This tool does not assume a 0% risk-free rate. It derives the actual
annualized T-bill return over the same window from BIL's own price history, so
Sharpe = (CAGR - T-bill rate) / volatility. Assuming zero inflates every Sharpe
ratio, and the error grows in high-rate periods. Windows that predate BIL's 2007
inception fall back to 0%. As rough intuition: below 0.5 is weak, 0.5-1.0 is decent
for a long-only passive portfolio, and above 1.0 over a long period is very good.
Sharpe ratios computed over short windows are noisy and should not be
over-interpreted.

## Sortino ratio

The Sortino ratio divides excess return by *downside* volatility only — the
standard deviation of losing days — rather than by total volatility. The reasoning
is that investors do not experience large upward moves as risk, so counting them
against a portfolio overstates how uncomfortable it actually was to hold. Because
it ignores upside swings, a Sortino figure always reads higher than the Sharpe
ratio for the same portfolio over the same window. Compare a Sortino only against
another Sortino, never across the two measures.

## Calmar ratio

The Calmar ratio is CAGR divided by the absolute size of the portfolio's deepest
peak-to-trough fall. It answers "how much annual return did this strategy deliver
per unit of worst-case pain?" Calmar is useful for comparing strategies an investor
has to actually live through: a portfolio returning 10% a year that never fell more
than 20% (Calmar 0.5) is far easier to hold than one returning 12% that once fell
60% (Calmar 0.2).

## Real (inflation-adjusted) CAGR

Real CAGR restates the annualized return in constant purchasing power:
(1 + CAGR) / (1 + inflation) - 1. A 7% nominal return in a 5% inflation year is
under 2% real. This tool computes inflation from BLS CPI-U annual averages, and
labels the result as estimated for periods after the last verified year in its
data file.

## Longest time underwater

Longest time underwater is the greatest number of days the portfolio spent below a
previous peak before recovering. Max drawdown tells you how deep the worst loss
was; this tells you how *long* it lasted. The two together describe an investor's
actual experience far better than either alone — a -30% drawdown that recovers in
six months is a very different thing from one that takes seven years.

## Max drawdown

Max drawdown is the largest peak-to-trough decline in portfolio value over the period,
expressed as a negative percentage. It answers "what is the worst loss an investor would
have experienced if they bought at the worst possible peak?" A 100% stock portfolio saw
drawdowns of roughly -55% in the 2008 financial crisis and -34% in the March 2020 COVID
crash. Drawdown matters because investors often abandon strategies during deep losses,
turning paper losses into permanent ones.

## Rebalancing

This tool models continuous rebalancing: portfolio weights are reset to their targets
every trading day. Real investors typically rebalance monthly, quarterly, or by
threshold bands. Continuous rebalancing is a reasonable approximation for backtests and
slightly overstates the "rebalancing bonus" from buying dips and trimming winners.
