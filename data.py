"""Price data layer: fetch from yfinance, cache to local parquet files."""
import time
from pathlib import Path
import pandas as pd
import yfinance as yf

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# Refresh cached history once it's older than this (seconds).
CACHE_MAX_AGE = 24 * 3600

# Tickers we support in v1. Keep this small and curated.
TICKERS = {
    "SPY": "S&P 500 (US Large Cap)",
    "AGG": "US Aggregate Bonds",
    "TLT": "20+ Year Treasury",
    "GLD": "Gold",
    "VTI": "US Total Stock Market",
    "VXUS": "International Stocks",
    "QQQ": "Nasdaq 100",
    "IEF": "7-10 Year Treasury",
    "VNQ": "US Real Estate",
    "BIL": "1-3 Month Treasury (Cash)",
}


def _cache_is_fresh(cache_file: Path) -> bool:
    return cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < CACHE_MAX_AGE


def load_prices(ticker: str, refresh: bool = False) -> pd.DataFrame:
    """Return a DataFrame with daily Close prices for `ticker`. Cached locally."""
    cache_file = CACHE_DIR / f"{ticker}.parquet"
    if _cache_is_fresh(cache_file) and not refresh:
        return pd.read_parquet(cache_file)

    try:
        df = yf.download(ticker, period="max", auto_adjust=True, progress=False)
    except Exception:
        df = pd.DataFrame()
    if df.empty:
        # Network/API failure: fall back to stale cache rather than dying.
        if cache_file.exists():
            return pd.read_parquet(cache_file)
        raise ValueError(f"No data returned for {ticker}")
    # yfinance multi-index when one ticker — flatten
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Close"]].rename(columns={"Close": ticker})
    df.to_parquet(cache_file)
    return df


def load_universe(refresh: bool = False) -> pd.DataFrame:
    """Load all supported tickers into one wide DataFrame indexed by date."""
    frames = [load_prices(t, refresh=refresh) for t in TICKERS]
    return pd.concat(frames, axis=1).dropna(how="all")


def get_quotes() -> list[dict]:
    """Latest price + daily change for every supported ticker, one batch call.

    Uses a 5-day window so it works on weekends/holidays. Prices from Yahoo
    are delayed ~15 min; this is market data display, not an execution feed.
    """
    df = yf.download(list(TICKERS), period="5d", auto_adjust=True, progress=False)
    closes = df["Close"].dropna(how="all")
    if len(closes) < 2:
        raise ValueError("Not enough recent data for quotes")
    last, prev = closes.iloc[-1], closes.iloc[-2]
    as_of = closes.index[-1].date().isoformat()
    quotes = []
    for t in TICKERS:
        if pd.isna(last.get(t)) or pd.isna(prev.get(t)):
            continue
        quotes.append({
            "ticker": t,
            "name": TICKERS[t],
            "price": round(float(last[t]), 2),
            "change_pct": round(float(last[t] / prev[t] - 1) * 100, 2),
            "as_of": as_of,
        })
    return quotes


if __name__ == "__main__":
    prices = load_universe()
    print(f"Loaded {len(prices)} rows, {len(prices.columns)} tickers")
    print(f"Date range: {prices.index.min().date()} → {prices.index.max().date()}")
    print()
    print(prices.tail())
