import numpy as np
import pandas as pd

from data import RANGES, TICKERS, period_returns


def _synthetic_universe(days=1400):
    dates = pd.bdate_range(start="2020-01-01", periods=days)
    up = 100 * (1.0005 ** np.arange(days))
    return pd.DataFrame({"SPY": up, "AGG": np.full(days, 100.0)}, index=dates)


def test_period_returns_shape():
    out = period_returns(_synthetic_universe())
    assert {f["ticker"] for f in out} == {"SPY", "AGG"}
    for f in out:
        assert set(f["returns"]) == set(RANGES)
        assert len(f["spark"]) == 30
        assert f["price"] > 0


def test_flat_asset_has_zero_returns():
    agg = next(f for f in period_returns(_synthetic_universe()) if f["ticker"] == "AGG")
    assert all(v == 0.0 for v in agg["returns"].values())


def test_rising_asset_returns_ordered():
    spy = next(f for f in period_returns(_synthetic_universe()) if f["ticker"] == "SPY")
    r = spy["returns"]
    assert 0 < r["1D"] < r["1W"] < r["1M"] < r["1Y"] < r["5Y"]


def test_short_history_clamps_to_start():
    df = _synthetic_universe(days=10)
    out = period_returns(df)
    spy = next(f for f in out if f["ticker"] == "SPY")
    # 1Y offset exceeds history: falls back to full-period return
    assert spy["returns"]["1Y"] == spy["returns"]["ALL"]


def test_ticker_metadata_complete():
    assert len(TICKERS) == 13
    assert all(isinstance(name, str) and name for name in TICKERS.values())


class _FakeTicker:
    """Stands in for yf.Ticker so the news tests never touch the network."""

    def __init__(self, items):
        self.news = items


def _item(url, title="Headline"):
    return {"content": {"title": title, "canonicalUrl": {"url": url},
                        "provider": {"displayName": "Somewhere"},
                        "pubDate": "2026-08-04T00:00:00Z"}}


def test_stock_news_drops_non_http_urls(monkeypatch):
    """The feed is third-party and its url is rendered into an href."""
    import data

    feed = [
        _item("javascript:alert(1)", "injected"),
        _item("data:text/html,<script>", "also injected"),
        _item("https://example.com/real", "kept"),
    ]
    monkeypatch.setattr(data.yf, "Ticker", lambda s: _FakeTicker(feed))
    data._news_cache.clear()

    items = data.stock_news("SPY")
    assert [i["title"] for i in items] == ["kept"]
    assert all(i["url"].startswith(("https://", "http://")) for i in items)


def test_stock_news_skips_items_missing_url_or_title(monkeypatch):
    import data

    feed = [
        {"content": {"title": "no url", "provider": {"displayName": "X"}}},
        _item("https://example.com/untitled", title=""),
        _item("https://example.com/ok", "ok"),
    ]
    monkeypatch.setattr(data.yf, "Ticker", lambda s: _FakeTicker(feed))
    data._news_cache.clear()

    assert [i["title"] for i in data.stock_news("SPY")] == ["ok"]
