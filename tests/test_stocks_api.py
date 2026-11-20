"""Stocks, watchlist, and Learn-article routes.

These were the last endpoints with no test coverage at all, which mattered
more than the number suggested: `/api/stocks/{symbol}/news` renders its `url`
straight into an `href` in both frontends, so it is the route most exposed to
third-party data.

Everything upstream is faked. `main` does `from data import ...`, so the names
are patched on `main`, not on `data` — patching `data` would leave `main`'s
already-bound reference untouched and the test would silently hit the network.
"""
import pytest
from fastapi.testclient import TestClient

import main
from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# /api/stocks/quotes
# ---------------------------------------------------------------------------
def test_quotes_returns_rows_enriched_with_catalog_names(monkeypatch):
    monkeypatch.setattr(
        main, "get_stock_quotes",
        lambda symbols: [{"symbol": s, "price": 100.0, "change": 1.5} for s in symbols],
    )
    r = client.get("/api/stocks/quotes?symbols=AAPL,MSFT")
    assert r.status_code == 200
    body = r.json()
    assert {q["symbol"] for q in body} == {"AAPL", "MSFT"}
    # The route's own job: the quote source knows prices, not display names.
    assert all(q["name"] for q in body)


def test_quotes_filters_unknown_symbols_but_keeps_known_ones(monkeypatch):
    seen = {}

    def record(symbols):
        seen["symbols"] = symbols
        return []

    monkeypatch.setattr(main, "get_stock_quotes", record)
    client.get("/api/stocks/quotes?symbols=AAPL,NOTAREALTICKER")
    assert seen["symbols"] == ["AAPL"]


def test_quotes_rejects_when_no_symbol_is_known():
    r = client.get("/api/stocks/quotes?symbols=NOTAREAL,ALSOFAKE")
    assert r.status_code == 422


def test_quotes_caps_the_request_at_thirty_symbols(monkeypatch):
    seen = {}

    def record(symbols):
        seen["n"] = len(symbols)
        return []

    monkeypatch.setattr(main, "get_stock_quotes", record)
    catalog = list(main.stock_catalog())[:40]
    client.get("/api/stocks/quotes?symbols=" + ",".join(catalog))
    # Unbounded fan-out to the quote provider is the thing being prevented.
    assert seen["n"] == 30


def test_quotes_surfaces_provider_failure_as_503(monkeypatch):
    def boom(symbols):
        raise RuntimeError("yahoo is down")

    monkeypatch.setattr(main, "get_stock_quotes", boom)
    r = client.get("/api/stocks/quotes?symbols=AAPL")
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# /api/stocks/{symbol}/history
# ---------------------------------------------------------------------------
def _fake_history(symbol, range_key="1Y", refresh=False):
    return {"symbol": symbol, "range": range_key, "dates": ["2026-01-02"], "close": [101.0]}


def test_history_returns_payload_with_catalog_metadata(monkeypatch):
    monkeypatch.setattr(main, "stock_history", _fake_history)
    body = client.get("/api/stocks/aapl/history?range=1M").json()
    assert body["symbol"] == "AAPL"          # normalised to upper case
    assert body["name"] == "Apple Inc."
    assert body["sector"]
    assert "1M" in body["ranges"]


def test_history_rejects_unknown_symbol():
    assert client.get("/api/stocks/NOTAREAL/history").status_code == 404


def test_history_rejects_unsupported_range():
    r = client.get("/api/stocks/AAPL/history?range=3Y")
    assert r.status_code == 422
    assert "range must be one of" in r.json()["detail"]


@pytest.mark.parametrize("range_key", sorted(main.STOCK_RANGES))
def test_history_accepts_every_documented_range(monkeypatch, range_key):
    monkeypatch.setattr(main, "stock_history", _fake_history)
    assert client.get(f"/api/stocks/AAPL/history?range={range_key}").status_code == 200


def test_history_surfaces_upstream_failure_as_503(monkeypatch):
    def boom(symbol, range_key="1Y", refresh=False):
        raise ValueError("no data for range")

    monkeypatch.setattr(main, "stock_history", boom)
    assert client.get("/api/stocks/AAPL/history").status_code == 503


# ---------------------------------------------------------------------------
# /api/stocks/{symbol}/news
# ---------------------------------------------------------------------------
def test_news_returns_items(monkeypatch):
    monkeypatch.setattr(
        main, "stock_news",
        lambda symbol, limit=8: [
            {"title": "Apple ships something", "publisher": "Reuters",
             "url": "https://example.com/a", "published": "2026-09-01T00:00:00Z"},
        ],
    )
    body = client.get("/api/stocks/AAPL/news").json()
    assert body["symbol"] == "AAPL"
    assert len(body["items"]) == 1


def test_news_rejects_unknown_symbol():
    assert client.get("/api/stocks/NOTAREAL/news").status_code == 404


def test_news_degrades_instead_of_failing_when_upstream_breaks(monkeypatch):
    def boom(symbol, limit=8):
        raise RuntimeError("feed unavailable")

    monkeypatch.setattr(main, "stock_news", boom)
    r = client.get("/api/stocks/AAPL/news")
    # News is decoration on the stock page; losing it must not 500 the page.
    assert r.status_code == 200
    assert r.json() == {"symbol": "AAPL", "items": [], "error": "News unavailable"}


def test_news_limit_is_bounded():
    assert client.get("/api/stocks/AAPL/news?limit=0").status_code == 422
    assert client.get("/api/stocks/AAPL/news?limit=21").status_code == 422


# ---------------------------------------------------------------------------
# /api/watchlist and /api/watchlist/{symbol}
# ---------------------------------------------------------------------------
def _logged_in_client(username):
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": username, "password": "s3cret-pass"})
    return c


def test_watchlist_requires_authentication():
    assert TestClient(app).get("/api/watchlist").status_code == 401


def test_watchlist_pin_then_unpin_roundtrip(monkeypatch):
    monkeypatch.setattr(main, "get_stock_quotes", lambda symbols: [])
    c = _logged_in_client("watchlist-user")

    assert c.get("/api/watchlist").json()["symbols"] == []

    c.post("/api/watchlist", json={"symbol": "aapl"})
    assert c.get("/api/watchlist").json()["symbols"] == ["AAPL"]  # normalised

    assert c.delete("/api/watchlist/aapl").json()["symbols"] == []


def test_watchlist_survives_a_dead_quote_provider(monkeypatch):
    def boom(symbols):
        raise RuntimeError("yahoo is down")

    monkeypatch.setattr(main, "get_stock_quotes", boom)
    c = _logged_in_client("watchlist-degraded")
    c.post("/api/watchlist", json={"symbol": "MSFT"})

    body = c.get("/api/watchlist").json()
    # The pinned symbols are the user's own data; they must survive the outage.
    assert body["symbols"] == ["MSFT"]
    assert body["quotes"] == []


# ---------------------------------------------------------------------------
# /api/learn/{slug}
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("slug", sorted(main.LEARN_ARTICLES))
def test_every_registered_article_resolves(slug):
    r = client.get(f"/api/learn/{slug}")
    assert r.status_code == 200
    assert r.json()["slug"] == slug


def test_unknown_article_slug_is_404():
    assert client.get("/api/learn/no-such-article").status_code == 404
