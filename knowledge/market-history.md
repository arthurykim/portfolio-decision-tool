# Notable market episodes in the data

## Dot-com crash (2000-2002)

After the late-1990s technology bubble, the Nasdaq 100 (QQQ) fell roughly -80% from
peak and the S&P 500 about -49%. Bonds rallied as the Fed cut rates, so balanced
portfolios fared far better than tech-heavy ones. Recovery to prior highs took the S&P
about 7 years, and QQQ about 15 years.

## Global financial crisis (2007-2009)

In the 2008 global financial crisis, the S&P 500 fell about -55% between October 2007
and March 2009. Real estate (VNQ) fell roughly -68%. Long-term Treasuries (TLT) rallied
strongly as investors fled to safety, which is why All Weather-style portfolios held up
comparatively well. A 60/40 portfolio drew down roughly -35% in 2008-2009.

## COVID crash (February-March 2020)

The fastest -30% drawdown in US history: the S&P 500 fell about -34% in five weeks,
then recovered to new highs within six months on massive fiscal and monetary stimulus.
TLT and gold both rallied during the panic.

## 2022 rate-shock bear market

With inflation peaking above 9%, the Fed raised rates rapidly. Stocks fell about -25%
and — unusually — bonds fell hard at the same time: AGG lost about -17% from its peak
and TLT more than -40% from its 2020 high. 2022 is the canonical example of
stock-bond correlation turning positive, the main failure mode of the 60/40 portfolio.
Gold was roughly flat, and cash (BIL) was one of the few safe places.

## Lessons for backtesting

Backtest windows matter enormously. A backtest starting in 2009 captures one of the
longest bull markets ever; starting in 2000 or 2007 captures deep crashes early.
Always test an allocation through at least one full crisis window before drawing
conclusions, and remember that past correlations (especially stock-bond) do not always
hold.
