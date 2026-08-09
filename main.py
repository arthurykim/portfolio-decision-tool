"""Portfolio Decision Tool — FastAPI backend.

Serves the JSON API under /api/* and the static frontend at /.
Run locally:  uvicorn main:app --reload
"""
import logging
import time
from pathlib import Path

from env import load_env

load_env()  # populate os.environ from .env before other modules read it

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import db
from auth import (
    USERNAME_RE,
    clear_session_cookie,
    current_user,
    hash_password,
    require_admin,
    require_user,
    set_session_cookie,
    verify_password,
)
from backtest import run_backtest
from data import (
    RANGES,
    STOCK_RANGES,
    TICKERS,
    annualized_inflation,
    get_movers,
    get_stock_quotes,
    index_history,
    load_universe,
    members_on,
    period_returns,
    risk_free_rate,
    stock_catalog,
    stock_history,
    stock_news,
    survivorship_gap,
)
from observability import metrics, new_request_id, request_id_var, setup_logging
from rag import _llm_available as llm_available
from rag import answer as rag_answer
from rag import get_index

setup_logging()
logger = logging.getLogger("app")

app = FastAPI(
    title="Portfolio Decision Tool API",
    version="1.0.0",
    description="Backtest capital allocations against real historical market data.",
)
db.init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # public read-only API; tighten if auth is ever added
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _prices() -> pd.DataFrame:
    return load_universe()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class BacktestRequest(BaseModel):
    allocation: dict[str, float] = Field(
        ..., description="Ticker → weight, weights sum to 1.0", min_length=1
    )
    start: str | None = Field(None, description="ISO date lower bound")
    end: str | None = Field(None, description="ISO date upper bound")

    @field_validator("allocation")
    @classmethod
    def _known_tickers_and_valid_weights(cls, v: dict[str, float]):
        unknown = [t for t in v if t not in TICKERS]
        if unknown:
            raise ValueError(f"Unsupported tickers: {unknown}")
        if any(w < 0 for w in v.values()):
            raise ValueError("Weights must be non-negative")
        total = sum(v.values())
        if abs(total - 1.0) > 1e-3:
            raise ValueError(f"Weights must sum to 1.0 (got {total:.4f})")
        return v


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


class Credentials(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)


class PinRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)


class AboutUpdate(BaseModel):
    content: str = Field(..., min_length=1, max_length=20000)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    """Liveness: is the process up? Deliberately dependency-free so a slow
    upstream never causes the orchestrator to restart a healthy container."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz(response: Response):
    """Readiness: can this instance actually serve traffic? Checks each
    dependency and reports which one is broken rather than a bare 503."""
    checks: dict[str, dict] = {}

    try:
        px = _prices()
        checks["prices"] = {"ok": True, "as_of": px.index[-1].date().isoformat(),
                            "rows": len(px), "tickers": len(px.columns)}
    except Exception as exc:
        checks["prices"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    try:
        with db.connect() as conn:
            conn.execute("SELECT 1").fetchone()
        checks["database"] = {"ok": True}
    except Exception as exc:
        checks["database"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    try:
        checks["knowledge_base"] = {"ok": True, "chunks": len(get_index().chunks)}
    except Exception as exc:
        checks["knowledge_base"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # Informational, never fatal: the chat degrades to extractive without a key.
    checks["llm"] = {"ok": True, "configured": llm_available(), "mode":
                     "gemini" if llm_available() else "extractive"}

    ready = all(c["ok"] for c in checks.values())
    if not ready:
        response.status_code = 503
    return {"ready": ready, "checks": checks}


@app.get("/metrics")
def prometheus_metrics():
    """Prometheus text exposition — scrape-compatible, no client library."""
    return Response(content=metrics.prometheus(), media_type="text/plain; version=0.0.4")


@app.get("/metrics.json")
def metrics_json():
    """Same counters as /metrics, readable without a Prometheus server."""
    return metrics.snapshot()


@app.get("/api/tickers")
def tickers():
    return [{"ticker": t, "name": n} for t, n in TICKERS.items()]


@app.get("/api/market")
def market():
    """Dashboard payload: per-ticker price + returns over every supported range."""
    px = _prices()
    return {
        "ranges": list(RANGES),
        "as_of": px.index[-1].date().isoformat(),
        "funds": period_returns(px),
    }


@app.get("/api/prices/{ticker}")
def prices(ticker: str, days: int = Query(365, ge=2, le=20000)):
    ticker = ticker.upper()
    if ticker not in TICKERS:
        raise HTTPException(status_code=404, detail=f"Unknown ticker {ticker}")
    px = _prices()[ticker].dropna().tail(days)
    return {
        "ticker": ticker,
        "dates": [d.date().isoformat() for d in px.index],
        "prices": [round(float(p), 2) for p in px],
    }


@app.get("/api/growth")
def growth(
    ticker: str = Query(...),
    amount: float = Query(..., ge=100, le=100_000_000),
    years: int = Query(..., ge=1, le=30),
):
    """Hypothetical lump-sum: what would $amount invested `years` ago be worth today?

    Purely historical arithmetic on adjusted closes — educational, not advice.
    """
    ticker = ticker.upper()
    if ticker not in TICKERS:
        raise HTTPException(status_code=404, detail=f"Unknown ticker {ticker}")
    px = _prices()[ticker].dropna()
    start = px.index[-1] - pd.DateOffset(years=years)
    window = px[px.index >= start]
    if len(window) < 2:
        raise HTTPException(
            status_code=422,
            detail=f"{ticker} data only goes back to {px.index[0].date()}",
        )
    curve = (window / window.iloc[0]) * amount
    if len(curve) > 1500:
        curve = curve.resample("W-FRI").last().dropna()
    actual_years = (window.index[-1] - window.index[0]).days / 365.25
    final = float(curve.iloc[-1])
    return {
        "ticker": ticker,
        "amount": amount,
        "start": window.index[0].date().isoformat(),
        "end": window.index[-1].date().isoformat(),
        "final_value": round(final, 2),
        "gain": round(final - amount, 2),
        "multiple": round(final / amount, 2),
        "cagr": round(((final / amount) ** (1 / actual_years) - 1) * 100, 2) if actual_years > 0 else 0,
        "curve": {
            "dates": [d.date().isoformat() for d in curve.index],
            "values": [round(float(v), 2) for v in curve],
        },
    }


BENCHMARK = "SPY"


def _downsample(series: pd.Series) -> pd.Series:
    """Weekly points keep charts snappy without visibly changing the shape."""
    return series.resample("W-FRI").last().dropna() if len(series) > 1500 else series


def _metrics(r) -> dict:
    return {
        "start": r.start.date().isoformat(),
        "end": r.end.date().isoformat(),
        "total_return": r.total_return,
        "cagr": r.cagr,
        "real_cagr": r.real_cagr,
        "volatility": r.volatility,
        "sharpe": r.sharpe,
        "sortino": r.sortino,
        "calmar": r.calmar,
        "max_drawdown": r.max_drawdown,
        "longest_drawdown_days": r.longest_drawdown_days,
        "risk_free_rate": r.risk_free_rate,
        "inflation_rate": r.inflation_rate,
    }


@app.post("/api/backtest")
def backtest(req: BacktestRequest):
    prices = _prices()
    rf = risk_free_rate(prices, req.start, req.end)
    inflation, inflation_estimated = annualized_inflation(req.start, req.end)
    try:
        result = run_backtest(
            prices, req.allocation, start=req.start, end=req.end,
            risk_free_rate=rf, inflation_rate=inflation,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    equity = _downsample(result.equity_curve)
    drawdown = equity / equity.cummax() - 1

    # Benchmark over the portfolio's actual (clipped) window, so it's comparable.
    benchmark = None
    if list(req.allocation) != [BENCHMARK]:
        try:
            # price_start (not start) so both equity curves begin the same day.
            bench = run_backtest(
                prices, {BENCHMARK: 1.0}, start=result.price_start, end=result.end,
                risk_free_rate=rf, inflation_rate=inflation,
            )
            bench_equity = _downsample(bench.equity_curve)
            benchmark = {
                "ticker": BENCHMARK,
                "name": TICKERS[BENCHMARK],
                "metrics": _metrics(bench),
                "equity_curve": {
                    "dates": [d.date().isoformat() for d in bench_equity.index],
                    "values": [round(float(v), 4) for v in bench_equity],
                },
            }
        except ValueError:
            benchmark = None  # window predates SPY; skip rather than fail

    return {
        "metrics": _metrics(result),
        "benchmark": benchmark,
        "inflation_estimated": inflation_estimated,
        "equity_curve": {
            "dates": [d.date().isoformat() for d in equity.index],
            "values": [round(float(v), 4) for v in equity],
        },
        "drawdown": {
            "dates": [d.date().isoformat() for d in drawdown.index],
            "values": [round(float(v), 4) for v in drawdown],
        },
    }


@app.post("/api/chat")
def chat(req: ChatRequest):
    try:
        result = rag_answer(req.message, [t.model_dump() for t in req.history])
    except Exception as exc:
        metrics.inc("chat_errors_total")
        logger.warning("Chat failed: %s", exc)
        raise HTTPException(status_code=500, detail="Chat unavailable") from exc
    # The key signal: a fallback to extractive means generation is degraded.
    metrics.inc("chat_answers_total", {"mode": result["mode"]})
    if result["mode"] != "gemini" and llm_available():
        metrics.inc("llm_fallbacks_total")
        logger.warning("Chat degraded to extractive despite a configured key")
    return result


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.post("/api/auth/register")
def register(creds: Credentials, response: Response):
    if not USERNAME_RE.match(creds.username):
        raise HTTPException(status_code=422, detail="Username: 3-32 letters, digits, . _ -")
    if db.get_user_by_name(creds.username):
        raise HTTPException(status_code=409, detail="Username already taken")
    user = db.create_user(creds.username, hash_password(creds.password))
    set_session_cookie(response, user["id"])
    return {"username": user["username"], "is_admin": user["is_admin"]}


@app.post("/api/auth/login")
def login(creds: Credentials, response: Response):
    row = db.get_user_by_name(creds.username)
    if row is None or not verify_password(creds.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    set_session_cookie(response, row["id"])
    return {"username": row["username"], "is_admin": bool(row["is_admin"])}


@app.post("/api/auth/logout")
def logout(response: Response):
    clear_session_cookie(response)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict | None = Depends(current_user)):
    return {"user": {"username": user["username"], "is_admin": user["is_admin"]} if user else None}


# ---------------------------------------------------------------------------
# Stocks & watchlist
# ---------------------------------------------------------------------------
@app.get("/api/stocks/quotes")
def stock_quotes(symbols: str = Query(..., max_length=400)):
    requested = [s.strip().upper() for s in symbols.split(",") if s.strip()][:30]
    catalog = stock_catalog()
    known = [s for s in requested if s in catalog]
    if not known:
        raise HTTPException(status_code=422, detail="No known symbols requested")
    try:
        quotes = get_stock_quotes(known)
    except Exception as exc:
        logger.warning("Stock quotes failed: %s", exc)
        raise HTTPException(status_code=503, detail="Quote source unavailable") from exc
    for q in quotes:
        q["name"] = catalog[q["symbol"]]["name"]
    return quotes


@app.get("/api/stocks/{symbol}/history")
def stock_detail(symbol: str, range: str = Query("1Y"), refresh: bool = False):
    """Price history and summary stats for one stock, fetched on demand.

    Not stored: 500 symbols x 8 ranges would be gigabytes that go stale hourly.
    """
    symbol = symbol.upper()
    catalog = stock_catalog()
    if symbol not in catalog and symbol not in TICKERS:
        raise HTTPException(status_code=404, detail=f"Unknown symbol {symbol}")
    if range.upper() not in STOCK_RANGES:
        raise HTTPException(
            status_code=422,
            detail=f"range must be one of {', '.join(STOCK_RANGES)}",
        )
    try:
        payload = stock_history(symbol, range, refresh=refresh)
    except ValueError as exc:
        metrics.inc("stock_history_errors_total", {"symbol": symbol})
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    payload["name"] = catalog.get(symbol, {}).get("name") or TICKERS.get(symbol, symbol)
    payload["sector"] = catalog.get(symbol, {}).get("sector", "")
    payload["ranges"] = list(STOCK_RANGES)
    metrics.inc("stock_history_total", {"range": range.upper()})
    return payload


@app.get("/api/stocks/{symbol}/news")
def stock_news_feed(symbol: str, limit: int = Query(8, ge=1, le=20)):
    """Recent headlines. Metadata and publisher links only — no article text."""
    symbol = symbol.upper()
    if symbol not in stock_catalog() and symbol not in TICKERS:
        raise HTTPException(status_code=404, detail=f"Unknown symbol {symbol}")
    try:
        items = stock_news(symbol, limit=limit)
    except Exception as exc:
        logger.warning("News fetch failed for %s: %s", symbol, exc)
        metrics.inc("news_errors_total")
        return {"symbol": symbol, "items": [], "error": "News unavailable"}
    metrics.inc("news_requests_total")
    return {"symbol": symbol, "items": items}


@app.get("/api/stocks/movers")
def stock_movers():
    """Top 5 gainers and losers across the S&P 500 catalog (1D change)."""
    try:
        return get_movers()
    except Exception as exc:
        logger.warning("Movers failed: %s", exc)
        raise HTTPException(status_code=503, detail="Quote source unavailable") from exc


@app.get("/api/index-history")
def index_history_summary(as_of: str = Query("2010-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")):
    """Point-in-time S&P 500 membership and the survivorship gap vs today."""
    hist = index_history()
    if not hist:
        raise HTTPException(
            status_code=503,
            detail="Index history not generated. Run scripts/build_index_history.py",
        )
    return {
        "source": hist["source"],
        "coverage_from": hist["coverage_from"],
        "changes": len(hist["changes"]),
        "survivorship": survivorship_gap(as_of),
        "members": members_on(as_of),
    }


@app.get("/api/watchlist")
def watchlist(user: dict = Depends(require_user)):
    symbols = db.get_watchlist(user["id"])
    quotes = []
    if symbols:
        try:
            quotes = stock_quotes(symbols=",".join(symbols))
        except HTTPException:
            quotes = []
    return {"symbols": symbols, "quotes": quotes}


@app.post("/api/watchlist")
def pin(req: PinRequest, user: dict = Depends(require_user)):
    symbol = req.symbol.strip().upper()
    if symbol not in stock_catalog() and symbol not in TICKERS:
        raise HTTPException(status_code=422, detail=f"Unknown symbol {symbol}")
    if len(db.get_watchlist(user["id"])) >= 30:
        raise HTTPException(status_code=422, detail="Watchlist is limited to 30 symbols")
    db.add_to_watchlist(user["id"], symbol)
    return {"symbols": db.get_watchlist(user["id"])}


@app.delete("/api/watchlist/{symbol}")
def unpin(symbol: str, user: dict = Depends(require_user)):
    db.remove_from_watchlist(user["id"], symbol.strip().upper())
    return {"symbols": db.get_watchlist(user["id"])}


# ---------------------------------------------------------------------------
# Learn articles
# ---------------------------------------------------------------------------
KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
LEARN_ARTICLES = {
    "what-are-etfs": "what-are-etfs.md",
    "what-are-index-funds": "what-are-index-funds.md",
    "retirement-accounts": "retirement-accounts.md",
    "taxable-vs-tax-advantaged": "taxable-vs-tax-advantaged.md",
    "hysa-vs-checking": "hysa-vs-checking.md",
    "money-basics": "money-basics.md",
    "what-is-trading": "what-is-trading.md",
    "how-leverage-works": "how-leverage-works.md",
    "capital-gains-and-taxes": "capital-gains-and-taxes.md",
    "odds-and-expected-value": "odds-and-expected-value.md",
}


def _article_meta(slug: str) -> dict:
    text = (KNOWLEDGE_DIR / LEARN_ARTICLES[slug]).read_text()
    lines = text.strip().splitlines()
    title = lines[0].lstrip("# ").strip()
    body = "\n".join(lines[1:]).strip()
    teaser = body.split("\n\n")[0].replace("\n", " ")
    return {
        "slug": slug,
        "title": title,
        "teaser": teaser,
        "image": f"/img/{slug}.svg",
        "content": text,
    }


@app.get("/api/learn")
def learn_index():
    return [
        {k: a[k] for k in ("slug", "title", "teaser", "image")}
        for a in (_article_meta(slug) for slug in LEARN_ARTICLES)
    ]


@app.get("/api/learn/{slug}")
def learn_article(slug: str):
    if slug not in LEARN_ARTICLES:
        raise HTTPException(status_code=404, detail="Unknown article")
    return _article_meta(slug)


# ---------------------------------------------------------------------------
# Editable content
# ---------------------------------------------------------------------------
@app.get("/api/about")
def about():
    return {"content": db.get_content("about") or ""}


@app.put("/api/about")
def update_about(req: AboutUpdate, user: dict = Depends(require_admin)):
    db.set_content("about", req.content)
    return {"content": req.content}


@app.middleware("http")
async def observe(request, call_next):
    """Correlate, time, and count every request."""
    request_id = request.headers.get("x-request-id") or new_request_id()
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        # Set here, not in an outer middleware: the contextvar is reset in the
        # finally block below, so anything outside this scope reads the default.
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        elapsed = time.perf_counter() - started
        # Use the route template, not the raw path, so /api/prices/{ticker}
        # is one metric series instead of one per ticker.
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        labels = {"method": request.method, "path": path, "status": str(status)}
        metrics.inc("http_requests_total", labels)
        metrics.observe("http_request_duration_seconds",
                        elapsed, {"method": request.method, "path": path})
        if status >= 500:
            metrics.inc("http_errors_total", {"path": path, "status": str(status)})
        logger.info(
            "%s %s %s %.1fms", request.method, request.url.path, status, elapsed * 1000,
            extra={"extra_fields": {
                "method": request.method, "path": request.url.path,
                "status": status, "duration_ms": round(elapsed * 1000, 1),
            }},
        )
        request_id_var.reset(token)


@app.middleware("http")
async def cache_headers(request, call_next):
    """HTML is never cached (so updates land immediately); versioned assets are immutable."""
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if "text/html" in content_type:
        response.headers["Cache-Control"] = "no-cache"
    elif "v=" in request.url.query:
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


# Static frontend last so /api/* wins routing.
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
