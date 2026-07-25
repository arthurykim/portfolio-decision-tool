"""Price data layer: fetch from yfinance, cache to local parquet files."""
import json
import os
import threading
import time
from pathlib import Path
import pandas as pd
import yfinance as yf

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# Refresh cached history once it's older than this (seconds). Default: hourly.
CACHE_MAX_AGE = int(os.environ.get("CACHE_MAX_AGE", 3600))

# Tickers we support in v1. Keep this small and curated.
TICKERS = {
    "SPY": "S&P 500 (US Large Cap)",
    "VOO": "S&P 500 (Vanguard)",
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


# Trading-day offsets for each supported range (None = special-cased).
RANGES = {"1D": 1, "1W": 5, "1M": 21, "YTD": None, "1Y": 252, "5Y": 1260, "ALL": None}


def period_returns(prices: pd.DataFrame) -> list[dict]:
    """Per-ticker % return over each supported range, from daily closes."""
    prices = prices.dropna(how="all")
    last_idx = prices.index[-1]
    out = []
    for t in prices.columns:
        px = prices[t].dropna()
        if len(px) < 2:
            continue
        last = float(px.iloc[-1])
        rets = {}
        for label, offset in RANGES.items():
            if label == "YTD":
                base = px[px.index < pd.Timestamp(year=last_idx.year, month=1, day=1)]
                ref = float(base.iloc[-1]) if len(base) else float(px.iloc[0])
            elif label == "ALL":
                ref = float(px.iloc[0])
            elif offset < len(px):
                ref = float(px.iloc[-1 - offset])
            else:
                ref = float(px.iloc[0])
            rets[label] = round((last / ref - 1) * 100, 2)
        spark = px.tail(30)
        out.append({
            "ticker": t,
            "name": TICKERS.get(t, t),
            "price": round(last, 2),
            "returns": rets,
            "since": px.index[0].date().isoformat(),
            "spark": [round(float(v), 2) for v in spark],
        })
    return out


# ---------------------------------------------------------------- stocks
STATIC_DATA = Path(__file__).parent / "static" / "data"
_stock_cache: dict[str, tuple[float, dict]] = {}
_stock_lock = threading.Lock()
STOCK_QUOTE_TTL = 600


def stock_catalog() -> dict[str, dict]:
    """All known stock symbols → {name, sector} from the catalog files."""
    catalog = {}
    for fname in ("sp500.json", "ipos.json"):
        payload = json.loads((STATIC_DATA / fname).read_text())
        for s in payload["stocks"]:
            catalog.setdefault(s["symbol"], {"name": s["name"], "sector": s.get("sector", "")})
    return catalog


def get_stock_quotes(symbols: list[str]) -> list[dict]:
    """Latest price + 1D change for catalog symbols. Batched, 10-min cache."""
    now = time.time()
    with _stock_lock:
        missing = [s for s in symbols if s not in _stock_cache or now - _stock_cache[s][0] > STOCK_QUOTE_TTL]
    # Chunked: Yahoo silently drops most tickers on very large batch requests.
    for i in range(0, len(missing), 100):
        chunk = missing[i:i + 100]
        try:
            df = yf.download(chunk, period="5d", auto_adjust=True, progress=False)
        except Exception:
            continue
        closes = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(columns={"Close": chunk[0]})
        closes = closes.dropna(how="all")
        if len(closes) < 2:
            continue
        last, prev = closes.iloc[-1], closes.iloc[-2]
        with _stock_lock:
            for s in chunk:
                if s in closes.columns and pd.notna(last.get(s)) and pd.notna(prev.get(s)):
                    _stock_cache[s] = (now, {
                        "symbol": s,
                        "price": round(float(last[s]), 2),
                        "change_pct": round(float(last[s] / prev[s] - 1) * 100, 2),
                    })
    with _stock_lock:
        return [_stock_cache[s][1] for s in symbols if s in _stock_cache]


_movers_cache: tuple[float, dict] | None = None


def rank_movers(quotes: list[dict], top: int = 5) -> dict:
    """Split quotes into the biggest 1D gainers and losers."""
    ranked = sorted(quotes, key=lambda q: q["change_pct"], reverse=True)
    return {"gainers": ranked[:top], "losers": ranked[-top:][::-1]}


def get_movers(top: int = 5) -> dict:
    """Top movers across the whole stock catalog, cached for STOCK_QUOTE_TTL."""
    global _movers_cache
    now = time.time()
    if _movers_cache and now - _movers_cache[0] < STOCK_QUOTE_TTL:
        return _movers_cache[1]
    catalog = stock_catalog()
    quotes = get_stock_quotes(list(catalog))
    if len(quotes) < 5:
        raise ValueError("insufficient quote coverage for movers")
    for q in quotes:
        q.setdefault("name", catalog.get(q["symbol"], {}).get("name", ""))
    movers = rank_movers(quotes, top=top)
    _movers_cache = (now, movers)
    return movers


if __name__ == "__main__":
    prices = load_universe()
    print(f"Loaded {len(prices)} rows, {len(prices.columns)} tickers")
    print(f"Date range: {prices.index.min().date()} → {prices.index.max().date()}")
    print()
    print(prices.tail())
