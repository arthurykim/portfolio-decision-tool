"""Backend tests for individual stocks. Pick the symbols on the command line:

    task test:stock                    # the default set below, offline
    task test:stock -- NVDA TSLA       # your symbols, offline (synthetic prices)
    task test:stock:live -- NVDA       # your symbols, real Yahoo Finance data
    pytest tests/test_stocks.py --stock NVDA [--live]

Or without a checkout: Actions tab -> "stock check" -> Run workflow.

Each test runs once per symbol and asserts what must hold for *any* stock: the
payload shape both frontends read, stats that agree with the points they
summarise, a window that matches the requested range. Because nothing depends
on particular prices, the same checks run against both data sources:

- Offline (the default, and what CI runs on every PR): Yahoo is replaced by
  tests/fake_yahoo.py. This proves the backend's handling of the symbol:
  catalog lookup, which Yahoo symbol and period/interval it asks for, parsing,
  stats. The prices are synthetic.
- --live: the same assertions against real Yahoo data, which is what answers
  "does NVDA actually work end to end right now?". Needs network access. If
  Yahoo is unreachable the run stops with an error rather than passing on
  nothing.

The tests at the bottom pin symbol-independent endpoint behaviour (caching,
404/422/503 paths) and always run offline.
"""
import json
import math
import re
import uuid
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from fake_yahoo import FakeYahoo
from fastapi.testclient import TestClient

import data
from data import STOCK_RANGES, TICKERS
from main import BENCHMARK, app

# One symbol per path a symbol can take through the backend: an S&P 500
# catalog stock, a recent IPO (short history, from ipos.json), a curated fund
# (also served by /api/prices, /api/growth and /api/backtest), and an index
# that Yahoo spells differently (SPX is ^GSPC there; see data.YF_SYMBOLS).
DEFAULT_SYMBOLS = ("AAPL", "RDDT", "SPY", "SPX")

# Same shape the watchlist accepts: 1-10 characters. Yahoo uses '-' for share
# classes (BRK-B), and the catalog follows it.
SYMBOL_RE = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,9}")

# Longest first-to-last span, in calendar days, a range may cover. Loose enough
# for holidays, tight enough that asking Yahoo for the wrong period fails.
MAX_SPAN_DAYS = {"1D": 0, "1W": 10, "1M": 35, "6M": 190, "1Y": 371, "5Y": 5 * 366 + 10}
# How stale the newest point may be. Monthly MAX bars carry the month's first
# day, so that range gets a month of slack.
MAX_AGE_DAYS = {"MAX": 40}
DEFAULT_MAX_AGE_DAYS = 10

IPO_LISTINGS = {
    s["symbol"]: s["ipo"]
    for s in json.loads((data.STATIC_DATA / "ipos.json").read_text())["stocks"]
}


def _selected_symbols(config) -> list[str]:
    raw = [s for opt in config.getoption("--stock") for s in re.split(r"[\s,]+", opt) if s]
    symbols = list(dict.fromkeys(s.upper() for s in raw)) or list(DEFAULT_SYMBOLS)
    bad = [s for s in symbols if not SYMBOL_RE.fullmatch(s)]
    if bad:
        raise pytest.UsageError(f"--stock: not a ticker symbol: {', '.join(bad)}")
    return symbols


def pytest_generate_tests(metafunc):
    if "symbol" in metafunc.fixturenames:
        symbols = _selected_symbols(metafunc.config)
        metafunc.parametrize("symbol", symbols, ids=symbols)


class _Recorder:
    """Stands in for `data.yf`, forwarding to the real or fake Yahoo and
    recording each request, so tests can assert what the backend asked for."""

    def __init__(self, backend):
        self.backend = backend
        self.calls: list[tuple] = []

    def download(self, tickers, **kwargs):
        self.calls.append((tickers, kwargs.get("period"), kwargs.get("interval", "1d")))
        return self.backend.download(tickers, **kwargs)

    def Ticker(self, symbol):  # noqa: N802 — mirrors yfinance
        self.calls.append((symbol, "news", None))
        return self.backend.Ticker(symbol)


# --- fixtures ---------------------------------------------------------------
@pytest.fixture(scope="module")
def backend(request, tmp_path_factory):
    """What the backend talks to for this module: real yfinance with --live,
    otherwise the offline stand-in."""
    if not request.config.getoption("--live"):
        yield FakeYahoo(listed=IPO_LISTINGS)
        return

    import yfinance

    try:
        probe = yfinance.download("SPY", period="5d", auto_adjust=True, progress=False)
    except Exception:
        probe = None
    if probe is None or probe.empty:
        pytest.exit("--live: Yahoo Finance is unreachable from here (a probe download "
                    "of SPY returned nothing). Check network access.", returncode=1)
    # The fund endpoints read the parquet price cache, which in a test run holds
    # synthetic prices (see conftest.py). Point them at an empty cache so they
    # fetch real history too, without overwriting the developer's own.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(data, "CACHE_DIR", tmp_path_factory.mktemp("live-prices"))
        yield yfinance


@pytest.fixture
def live(backend) -> bool:
    return not isinstance(backend, FakeYahoo)


def _clear_stock_caches():
    for cache in (data._history_cache, data._news_cache, data._stock_cache):
        cache.clear()


@pytest.fixture(autouse=True)
def yahoo(backend, monkeypatch):
    """Autouse, so no test in this module can reach Yahoo by accident."""
    _clear_stock_caches()
    recorder = _Recorder(backend)
    monkeypatch.setattr(data, "yf", recorder)
    yield recorder
    _clear_stock_caches()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def catalog():
    return data.stock_catalog()


@pytest.fixture
def served(symbol, catalog):
    """`symbol`, skipping when the backend does not serve it at all.
    test_symbol_is_served reports that case once, as a failure."""
    if symbol not in catalog and symbol not in TICKERS:
        pytest.skip(f"{symbol} is not served by the backend (see test_symbol_is_served)")
    return symbol


@pytest.fixture
def fund(served):
    if served not in TICKERS:
        pytest.skip(f"/api/prices, /api/growth and backtests cover the {len(TICKERS)} "
                    f"curated funds; {served} is not one of them")
    return served


def _yahoo_symbol(symbol: str) -> str:
    return data.YF_SYMBOLS.get(symbol, symbol)


# --- per-symbol: is it served? ---------------------------------------------
def test_symbol_is_served(symbol, catalog):
    assert symbol in catalog or symbol in TICKERS, (
        f"{symbol} is not in the stock catalog, so every /api/stocks/{symbol}/... route "
        "returns 404. To serve it, add it to static/data/sp500.json or static/data/ipos.json."
    )


# --- per-symbol: price history, every range ---------------------------------
def _parse_stamp(t: str, intraday: bool) -> datetime:
    if intraday:
        stamp = datetime.fromisoformat(t)
        assert stamp.tzinfo is not None, f"intraday timestamp without a timezone: {t}"
        return stamp
    assert len(t) == 10, f"daily point should be a bare date, got {t}"
    return datetime.combine(date.fromisoformat(t), datetime.min.time())


def _assert_window(symbol: str, range_key: str, points: list[dict]):
    # Both frontends label the chart with t[:10], so that is the date that counts.
    days = [date.fromisoformat(p["t"][:10]) for p in points]
    span = (days[-1] - days[0]).days
    if range_key in MAX_SPAN_DAYS:
        assert span <= MAX_SPAN_DAYS[range_key], f"{range_key} covers {span} days"
    if range_key == "YTD":
        assert days[0] >= date(days[-1].year, 1, 1) - timedelta(days=7), days[0]
    if range_key == "MAX" and symbol in IPO_LISTINGS:
        listed = pd.Timestamp(IPO_LISTINGS[symbol]).date()
        assert days[0] >= listed - timedelta(days=31), (
            f"history starts {days[0]}, before the catalog's IPO date {listed}")
    age = (date.today() - days[-1]).days
    assert age <= MAX_AGE_DAYS.get(range_key, DEFAULT_MAX_AGE_DAYS), (
        f"newest point is {age} days old ({days[-1]})")


def _assert_stats(stats: dict, closes: list[float]):
    # Both frontends call .toFixed() on these, which throws on null.
    for key in ("price", "change", "change_pct", "high", "low", "open"):
        assert isinstance(stats[key], int | float) and math.isfinite(stats[key]), key
    first, last = closes[0], closes[-1]
    assert stats["points"] == len(closes)
    assert stats["price"] == pytest.approx(last, abs=0.006)
    assert stats["open"] == pytest.approx(first, abs=0.006)
    assert stats["high"] == pytest.approx(max(closes), abs=0.006)
    assert stats["low"] == pytest.approx(min(closes), abs=0.006)
    assert stats["low"] <= min(stats["open"], stats["price"])
    assert max(stats["open"], stats["price"]) <= stats["high"]
    assert stats["change"] == pytest.approx(last - first, abs=0.011)
    assert stats["change_pct"] == pytest.approx((last / first - 1) * 100, abs=0.02)
    assert stats["volume"] is None or (isinstance(stats["volume"], int) and stats["volume"] >= 0)


@pytest.mark.parametrize("range_key", list(STOCK_RANGES))
def test_history(client, yahoo, served, range_key, catalog):
    r = client.get(f"/api/stocks/{served}/history", params={"range": range_key})
    assert r.status_code == 200, r.text
    body = r.json()
    period, interval = STOCK_RANGES[range_key]

    assert yahoo.calls == [(_yahoo_symbol(served), period, interval)], (
        "asked Yahoo for the wrong instrument or window")

    assert body["symbol"] == served
    assert (body["range"], body["interval"]) == (range_key, interval)
    assert body["ranges"] == list(STOCK_RANGES)
    assert body["name"] == (catalog.get(served, {}).get("name") or TICKERS[served])
    assert body["sector"] == catalog.get(served, {}).get("sector", "")

    points = body["points"]
    assert points, "no price points"
    closes = [p["c"] for p in points]
    assert all(isinstance(c, int | float) and math.isfinite(c) and c > 0 for c in closes)
    stamps = [_parse_stamp(p["t"], intraday=interval.endswith("m")) for p in points]
    assert all(a < b for a, b in zip(stamps, stamps[1:], strict=False)), (
        "timestamps must strictly increase")

    _assert_window(served, range_key, points)
    _assert_stats(body["stats"], closes)


# --- per-symbol: news, quote, watchlist -------------------------------------
def test_news(client, yahoo, served, live):
    r = client.get(f"/api/stocks/{served}/news", params={"limit": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbol"] == served
    assert "error" not in body, body.get("error")
    assert yahoo.calls == [(_yahoo_symbol(served), "news", None)]

    items = body["items"]
    assert len(items) <= 5
    if not live:
        assert len(items) == 5, "the stand-in always has headlines; this must not pass on nothing"
    for item in items:
        assert item["title"] and len(item["title"]) <= 200
        assert item["publisher"]
        assert isinstance(item["published"], str)
        # Rendered into an href by both frontends.
        assert item["url"].startswith(("https://", "http://")), item["url"]


def test_quote(client, served, catalog):
    if served not in catalog:
        pytest.skip(f"/api/stocks/quotes covers catalog stocks; {served} is a fund or index")
    r = client.get("/api/stocks/quotes", params={"symbols": served})
    assert r.status_code == 200, r.text
    quotes = r.json()
    assert len(quotes) == 1, f"no quote came back for {served}"
    quote = quotes[0]
    assert (quote["symbol"], quote["name"]) == (served, catalog[served]["name"])
    assert quote["price"] > 0
    assert math.isfinite(quote["change_pct"])


def test_watchlist_pin_and_unpin(served):
    c = TestClient(app)  # its own cookie jar: this test logs in
    user = f"stk-{uuid.uuid4().hex[:12]}"
    assert c.post("/api/auth/register", json={"username": user, "password": "correct-horse"}).status_code == 200
    assert served in c.post("/api/watchlist", json={"symbol": served.lower()}).json()["symbols"]
    assert served not in c.delete(f"/api/watchlist/{served}").json()["symbols"]


# --- per-symbol: the curated funds' endpoints --------------------------------
def test_fund_prices(client, fund):
    r = client.get(f"/api/prices/{fund}", params={"days": 30})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ticker"] == fund
    assert len(body["dates"]) == len(body["prices"]) == 30
    assert body["dates"] == sorted(body["dates"])
    assert all(p > 0 for p in body["prices"])


def test_fund_growth(client, fund):
    r = client.get("/api/growth", params={"ticker": fund, "amount": 10_000, "years": 1})
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["start"] < g["end"]
    assert g["final_value"] > 0
    assert g["gain"] == pytest.approx(g["final_value"] - 10_000, abs=0.011)
    assert len(g["curve"]["dates"]) == len(g["curve"]["values"])


def test_fund_backtest(client, fund):
    r = client.post("/api/backtest", json={"allocation": {fund: 1.0}})
    assert r.status_code == 200, r.text
    body = r.json()
    m = body["metrics"]
    assert m["start"] < m["end"]
    assert -1 <= m["max_drawdown"] <= 0
    assert m["volatility"] >= 0
    for key in ("total_return", "cagr", "real_cagr", "sharpe", "sortino", "calmar"):
        assert math.isfinite(m[key]), key
    # The benchmark is SPY; comparing SPY against itself is omitted.
    assert (body["benchmark"] is None) == (fund == BENCHMARK)


# --- endpoint behaviour, independent of the symbol (always offline) ----------
@pytest.fixture
def fake(monkeypatch):
    """A fresh offline Yahoo even under --live: these pin backend behaviour, not data."""
    recorder = _Recorder(FakeYahoo(listed=IPO_LISTINGS))
    monkeypatch.setattr(data, "yf", recorder)
    return recorder


def test_symbol_lookup_is_case_insensitive(client, fake):
    body = client.get("/api/stocks/aapl/history", params={"range": "1M"}).json()
    assert body["symbol"] == "AAPL"
    assert fake.calls[0][0] == "AAPL"


def test_history_is_cached_until_refresh(client, fake):
    url = "/api/stocks/AAPL/history"
    first = client.get(url, params={"range": "1M"}).json()
    again = client.get(url, params={"range": "1M"}).json()
    assert again == first
    assert len(fake.calls) == 1, "a repeat view should come from the cache"

    client.get(url, params={"range": "1M", "refresh": "true"})
    assert len(fake.calls) == 2, "refresh=true must bypass the cache"


def test_unserved_symbol_is_rejected_without_asking_yahoo(client, fake):
    assert client.get("/api/stocks/ZZZZ/history").status_code == 404
    assert client.get("/api/stocks/ZZZZ/news").status_code == 404
    assert client.get("/api/stocks/quotes", params={"symbols": "ZZZZ"}).status_code == 422
    assert fake.calls == []


def test_unknown_range_is_rejected_without_asking_yahoo(client, fake):
    r = client.get("/api/stocks/AAPL/history", params={"range": "2Y"})
    assert r.status_code == 422
    assert "1D" in r.json()["detail"]
    assert fake.calls == []


def test_no_data_from_yahoo_is_a_503_not_a_500(client, monkeypatch):
    monkeypatch.setattr(data, "yf", _Recorder(FakeYahoo(missing={"AAPL"})))
    r = client.get("/api/stocks/AAPL/history", params={"range": "1M"})
    assert r.status_code == 503
    assert "AAPL" in r.json()["detail"]


def test_news_failure_degrades_to_an_empty_list(client, monkeypatch):
    class _Broken:
        def Ticker(self, symbol):  # noqa: N802
            raise ConnectionError("yahoo is down")

    monkeypatch.setattr(data, "yf", _Broken())
    r = client.get("/api/stocks/AAPL/news")
    assert r.status_code == 200
    assert r.json() == {"symbol": "AAPL", "items": [], "error": "News unavailable"}
