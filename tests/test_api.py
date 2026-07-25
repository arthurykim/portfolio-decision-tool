"""API tests. Uses the locally cached price data (no network required)."""
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_healthz():
    assert client.get("/healthz").json() == {"status": "ok"}


def test_tickers():
    data = client.get("/api/tickers").json()
    assert len(data) == 11
    assert {"ticker": "SPY", "name": "S&P 500 (US Large Cap)"} in data


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
    assert len(body["funds"]) == 11
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


def test_chat_returns_answer_and_sources():
    r = client.post("/api/chat", json={"message": "What is max drawdown?"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] in ("claude", "extractive")
    assert "drawdown" in body["answer"].lower()
    assert any(s["source"] == "metrics.md" for s in body["sources"])


def test_chat_rejects_empty_message():
    assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_frontend_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "Portfolio Decision Tool" in r.text
