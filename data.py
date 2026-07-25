"""Price data layer: fetch from yfinance, cache to local parquet files."""
import json
import os
import threading
import time
from functools import lru_cache
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
    # Drop rows with no close: the current session's bar can come back empty,
    # which would otherwise make "as of" report a date that has no price.
    df = df[["Close"]].rename(columns={"Close": ticker}).dropna()
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


# ---------------------------------------------------------------- rates
CPI_FILE = Path(__file__).parent / "data" / "cpi.json"
RISK_FREE_TICKER = "BIL"  # 1-3 month T-bills stand in for the risk-free rate


def _annualized(series: pd.Series) -> float:
    years = (series.index[-1] - series.index[0]).days / 365.25
    if years <= 0 or series.iloc[0] <= 0:
        return 0.0
    return float((series.iloc[-1] / series.iloc[0]) ** (1 / years) - 1)


def risk_free_rate(prices: pd.DataFrame, start=None, end=None) -> float:
    """Annualized T-bill return over the window, from BIL's own price history.

    Returns 0.0 when the window predates BIL (2007) so callers degrade to the
    old rf=0 behaviour rather than failing.
    """
    if RISK_FREE_TICKER not in prices.columns:
        return 0.0
    px = prices[RISK_FREE_TICKER].dropna()
    if start is not None:
        px = px[px.index >= pd.Timestamp(start)]
    if end is not None:
        px = px[px.index <= pd.Timestamp(end)]
    return _annualized(px) if len(px) >= 2 else 0.0


@lru_cache(maxsize=1)
def _cpi() -> dict:
    payload = json.loads(CPI_FILE.read_text())
    payload["annual"] = {int(y): v for y, v in payload["annual"].items()}
    return payload


def _cpi_for_year(year: int) -> float:
    """CPI index for a year, extrapolating past the last verified BLS value."""
    cpi = _cpi()
    annual, last = cpi["annual"], cpi["last_verified_year"]
    if year in annual:
        return annual[year]
    if year > last:
        return annual[last] * (1 + cpi["assumed_rate_after_last_verified"]) ** (year - last)
    return annual[min(annual)]


def annualized_inflation(start=None, end=None) -> tuple[float, bool]:
    """(annualized CPI growth over the window, whether any of it was estimated)."""
    cpi = _cpi()
    today = pd.Timestamp.today()
    start_ts = pd.Timestamp(start) if start is not None else pd.Timestamp("1990-01-01")
    end_ts = pd.Timestamp(end) if end is not None else today
    years = (end_ts - start_ts).days / 365.25
    if years <= 0:
        return 0.0, False
    ratio = _cpi_for_year(end_ts.year) / _cpi_for_year(start_ts.year)
    estimated = end_ts.year > cpi["last_verified_year"]
    return float(ratio ** (1 / years) - 1), estimated


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
