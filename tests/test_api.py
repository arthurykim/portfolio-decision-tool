"""API tests. Uses the locally cached price data (no network required)."""
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_healthz():
    assert client.get("/healthz").json() == {"status": "ok"}


def test_tickers():
    data = client.get("/api/tickers").json()
    assert len(data) == 13
    assert {"ticker": "SPY", "name": "S&P 500 (US Large Cap)"} in data
    assert {"ticker": "SPX", "name": "S&P 500 (Index)"} in data
    assert {"ticker": "NDX", "name": "Nasdaq 100 (Index)"} in data


def test_prices():
    r = client.get("/api/prices/SPY?days=30")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "SPY"
    assert len(body["prices"]) == 30
    assert len(body["dates"]) == 30


def test_prices_unknown_ticker():
    assert client.get("/api/prices/FAKE").status_code == 404


def test_backtest_60_40():
    r = client.post("/api/backtest", json={"allocation": {"SPY": 0.6, "AGG": 0.4}})
    assert r.status_code == 200
    body = r.json()
    m = body["metrics"]
    assert -1 < m["max_drawdown"] < 0
    assert m["cagr"] > 0  # 60/40 has been positive over its full history
    assert len(body["equity_curve"]["dates"]) == len(body["equity_curve"]["values"])
    assert len(body["drawdown"]["dates"]) > 0


def test_backtest_returns_risk_metrics_and_benchmark():
    r = client.post("/api/backtest", json={"allocation": {"SPY": 0.6, "AGG": 0.4}})
    body = r.json()
    m = body["metrics"]
    for field in ("real_cagr", "sortino", "calmar", "longest_drawdown_days",
                  "risk_free_rate", "inflation_rate"):
        assert field in m, field
    assert m["real_cagr"] < m["cagr"]           # inflation drags nominal down
    assert m["risk_free_rate"] > 0              # derived from BIL, not hardcoded 0
    assert m["longest_drawdown_days"] > 0

    bench = body["benchmark"]
    assert bench["ticker"] == "SPY"
    # Benchmark must cover the same window to be comparable.
    assert bench["metrics"]["start"] == m["start"]
    assert bench["metrics"]["end"] == m["end"]


def test_backtest_omits_benchmark_when_portfolio_is_the_benchmark():
    body = client.post("/api/backtest", json={"allocation": {"SPY": 1.0}}).json()
    assert body["benchmark"] is None


def test_backtest_rejects_bad_weights():
    r = client.post("/api/backtest", json={"allocation": {"SPY": 0.9}})
    assert r.status_code == 422


def test_backtest_rejects_unknown_ticker():
    r = client.post("/api/backtest", json={"allocation": {"FAKE": 1.0}})
    assert r.status_code == 422


def test_backtest_rejects_negative_weight():
    r = client.post("/api/backtest", json={"allocation": {"SPY": 1.5, "AGG": -0.5}})
    assert r.status_code == 422


def test_market_dashboard():
    r = client.get("/api/market")
    assert r.status_code == 200
    body = r.json()
    assert body["ranges"] == ["1D", "1W", "1M", "YTD", "1Y", "5Y", "ALL"]
    assert len(body["funds"]) == 13
    spy = next(f for f in body["funds"] if f["ticker"] == "SPY")
    assert spy["price"] > 0
    assert set(spy["returns"]) == set(body["ranges"])
    assert len(spy["spark"]) == 30


def test_growth_calculator():
    r = client.get("/api/growth?ticker=SPY&amount=1000&years=10")
    assert r.status_code == 200
    g = r.json()
    assert g["final_value"] > 0
    assert g["gain"] == round(g["final_value"] - 1000, 2)
    assert len(g["curve"]["dates"]) == len(g["curve"]["values"])


def test_growth_clamps_to_available_history():
    r = client.get("/api/growth?ticker=VXUS&amount=1000&years=30")
    assert r.status_code == 200
    assert r.json()["start"] >= "2011-01-01"  # VXUS inception


def test_growth_validates_inputs():
    assert client.get("/api/growth?ticker=SPY&amount=50&years=10").status_code == 422
    assert client.get("/api/growth?ticker=SPY&amount=200000000&years=10").status_code == 422
    assert client.get("/api/growth?ticker=SPY&amount=1000&years=50").status_code == 422
    assert client.get("/api/growth?ticker=FAKE&amount=1000&years=10").status_code == 404


def test_growth_accepts_large_amounts():
    r = client.get("/api/growth?ticker=SPY&amount=100000000&years=5")
    assert r.status_code == 200
    assert r.json()["final_value"] > 100_000_000 * 0.1  # sane output for $100M


def test_learn_index_and_articles():
    articles = client.get("/api/learn").json()
    # Compared against the registry rather than a hard-coded count, so adding an
    # article does not fail this test — but forgetting to register one does.
    from main import LEARN_ARTICLES

    assert {a["slug"] for a in articles} == set(LEARN_ARTICLES)
    assert {a["slug"] for a in articles} >= {
        "what-are-etfs", "what-are-index-funds",
        "retirement-accounts", "taxable-vs-tax-advantaged",
        "hysa-vs-checking", "money-basics",
        "what-is-trading", "how-leverage-works",
        "capital-gains-and-taxes", "odds-and-expected-value",
    }
    assert all(a["title"] and a["teaser"] for a in articles)


def test_every_learn_article_has_a_hero_image():
    # The Learn tiles render article["image"] unconditionally, so a missing file
    # is a broken image on the live page rather than a caught error.
    from pathlib import Path

    for article in client.get("/api/learn").json():
        path = Path(__file__).resolve().parents[1] / "static" / article["image"].lstrip("/")
        assert path.exists(), f"missing hero image for {article['slug']}: {path}"

    etfs = client.get("/api/learn/what-are-etfs").json()
    assert etfs["title"] == "What are ETFs?"
    assert "exchange-traded fund" in etfs["content"]
    assert client.get("/api/learn/nope").status_code == 404


def test_movers_ranks_gainers_and_losers(monkeypatch):
    fake = [
        {"symbol": s, "price": 100.0, "change_pct": pct, "name": s}
        for s, pct in [("AAA", 5.0), ("BBB", -3.0), ("CCC", 1.0),
                       ("DDD", -7.0), ("EEE", 2.0), ("FFF", 0.5), ("GGG", -1.0)]
    ]
    import data
    monkeypatch.setattr(data, "_movers_cache", None)
    monkeypatch.setattr(data, "get_stock_quotes", lambda symbols: fake)
    m = client.get("/api/stocks/movers").json()
    assert [q["symbol"] for q in m["gainers"]] == ["AAA", "EEE", "CCC", "FFF", "GGG"]
    assert [q["symbol"] for q in m["losers"]] == ["DDD", "BBB", "GGG", "FFF", "CCC"]


def test_chat_returns_answer_and_sources():
    r = client.post("/api/chat", json={"message": "What is max drawdown?"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] in ("gemini", "extractive")
    assert "drawdown" in body["answer"].lower()
    assert any(s["source"] == "metrics.md" for s in body["sources"])


def test_chat_rejects_empty_message():
    assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_frontend_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "Portfolio Decision Tool" in r.text
