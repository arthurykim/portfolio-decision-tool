"""An offline, deterministic stand-in for the slice of yfinance the backend uses.

`data.py` reaches Yahoo through exactly two yfinance entry points:
`yf.download(...)` for prices and `yf.Ticker(symbol).news` for headlines. This
fakes both, returning frames shaped the way yfinance 1.x returns them — a
(Price, Ticker) MultiIndex on the columns, a tz-aware exchange-time index for
intraday intervals, naive dates for daily and longer — so the backend's parsing
code runs unchanged against it.

Prices are a random walk seeded from the symbol, so a failure reproduces on any
machine, and history respects listing dates: a stock that listed last March has
no five-year chart here, just as it has none on Yahoo.
"""
import zlib

import numpy as np
import pandas as pd

EXCHANGE_TZ = "America/New_York"
SESSION_OPEN, SESSION_CLOSE = "09:30", "16:00"
DEFAULT_LISTING = "1990-01-02"

# How far back each yfinance `period` reaches from the last session.
_LOOKBACK = {
    "1mo": pd.DateOffset(months=1),
    "6mo": pd.DateOffset(months=6),
    "1y": pd.DateOffset(years=1),
    "5y": pd.DateOffset(years=5),
}
# Periods measured in trading sessions rather than calendar time.
_SESSIONS = {"1d": 1, "5d": 5}
_BAR_FREQ = {"1d": "B", "1wk": "W-MON", "1mo": "MS"}


def _seed(*parts: str) -> int:
    # zlib.crc32, not hash(): str hashing is salted per process.
    return zlib.crc32("|".join(parts).encode())


class FakeYahoo:
    """Drop-in for the `yf` module as `data.py` uses it.

    `listed` maps symbol -> listing date ("YYYY-MM" or "YYYY-MM-DD"); anything
    absent gets a long history. Symbols in `missing` come back empty, the way
    yfinance reports a delisted or unknown ticker.
    """

    def __init__(self, listed: dict[str, str] | None = None, missing=(), today=None):
        self.listed = dict(listed or {})
        self.missing = set(missing)
        self.today = pd.Timestamp(today) if today else pd.Timestamp.now(tz=EXCHANGE_TZ).tz_localize(None)

    # -- yf.download ---------------------------------------------------------
    def download(self, tickers, period="1mo", interval="1d", **_kwargs) -> pd.DataFrame:
        symbols = [tickers] if isinstance(tickers, str) else list(tickers)
        frames = {
            s: self._bars(s, period, interval) for s in symbols if s not in self.missing
        }
        frames = {s: f for s, f in frames.items() if not f.empty}
        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames, axis=1)  # columns: (Ticker, Price)
        out.columns = out.columns.swaplevel(0, 1)
        out.columns.names = ["Price", "Ticker"]
        return out.sort_index(axis=1, level=0, sort_remaining=False)

    # -- yf.Ticker(symbol).news ----------------------------------------------
    def Ticker(self, symbol: str) -> "_FakeTicker":  # noqa: N802 — mirrors yfinance
        return _FakeTicker(symbol, self)

    # -- internals -----------------------------------------------------------
    def _last_session(self) -> pd.Timestamp:
        day = self.today.normalize()
        while day.dayofweek >= 5:
            day -= pd.Timedelta(days=1)
        return day

    def _index(self, symbol: str, period: str, interval: str) -> pd.DatetimeIndex:
        end = self._last_session()
        listed = pd.Timestamp(self.listed.get(symbol, DEFAULT_LISTING))

        if interval.endswith("m"):
            sessions = pd.bdate_range(end=end, periods=_SESSIONS[period])
            sessions = sessions[sessions >= listed]
            stamps = [
                t
                for day in sessions
                for t in pd.date_range(
                    f"{day.date()} {SESSION_OPEN}", f"{day.date()} {SESSION_CLOSE}",
                    freq=interval.replace("m", "min"), inclusive="left",
                )
            ]
            index = pd.DatetimeIndex(stamps).tz_localize(EXCHANGE_TZ)
            index.name = "Datetime"
            return index

        if period in _SESSIONS:
            start = pd.bdate_range(end=end, periods=_SESSIONS[period])[0]
        elif period == "max":
            start = listed
        elif period == "ytd":
            start = pd.Timestamp(year=end.year, month=1, day=1)
        else:
            start = end - _LOOKBACK[period]
        index = pd.date_range(max(start, listed), end, freq=_BAR_FREQ[interval])
        index.name = "Date"
        return index

    def _bars(self, symbol: str, period: str, interval: str) -> pd.DataFrame:
        index = self._index(symbol, period, interval)
        n = len(index)
        if n == 0:
            return pd.DataFrame()
        rng = np.random.default_rng(_seed(symbol, period, interval))
        base = 20 + _seed(symbol) % 480
        close = base * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))
        open_ = np.concatenate([[base], close[:-1]]) * (1 + rng.normal(0, 0.002, n))
        wiggle = np.abs(rng.normal(0, 0.004, n))
        return pd.DataFrame(
            {
                "Close": close,
                "High": np.maximum(open_, close) * (1 + wiggle),
                "Low": np.minimum(open_, close) * (1 - wiggle),
                "Open": open_,
                "Volume": rng.integers(100_000, 5_000_000, n),
            },
            index=index,
        )


class _FakeTicker:
    def __init__(self, symbol: str, yahoo: FakeYahoo):
        self.symbol = symbol
        self._yahoo = yahoo

    @property
    def news(self) -> list[dict]:
        if self.symbol in self._yahoo.missing:
            return []
        # yfinance 1.x shape: the useful fields sit under "content".
        now = self._yahoo.today
        return [
            {
                "id": f"{self.symbol}-{i}",
                "content": {
                    "title": f"{self.symbol} headline {i}",
                    "pubDate": (now - pd.Timedelta(hours=3 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "provider": {"displayName": ("Reuters", "Bloomberg", "AP")[i % 3]},
                    "canonicalUrl": {"url": f"https://news.example.com/{self.symbol.lower()}/{i}"},
                },
            }
            for i in range(10)
        ]
