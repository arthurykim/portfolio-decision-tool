"""Portfolio Decision Tool — FastAPI backend: JSON API under /api/*, static frontend at /."""
import logging
import time
from pathlib import Path

from env import load_env

load_env()  # populate os.environ from .env before other modules read it

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
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
    annualized_return,
    get_movers,
    get_stock_quotes,
    index_history,
    is_known_symbol,
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
from rag import KNOWLEDGE_DIR, get_index
from rag import _llm_available as llm_available
from rag import answer as rag_answer

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


def _require_ticker(ticker: str) -> str:
    ticker = ticker.upper()
    if ticker not in TICKERS:
        raise HTTPException(status_code=404, detail=f"Unknown ticker {ticker}")
    return ticker


def _require_symbol(symbol: str, status_code: int = 404) -> str:
    symbol = symbol.strip().upper()
    if not is_known_symbol(symbol):
        raise HTTPException(status_code=status_code, detail=f"Unknown symbol {symbol}")
    return symbol


def _downsample(series: pd.Series) -> pd.Series:
    # Weekly points keep long charts light without visibly changing their shape.
    return series.resample("W-FRI").last().dropna() if len(series) > 1500 else series


def _series(series: pd.Series, ndigits: int = 4) -> dict:
    return {
        "dates": [d.date().isoformat() for d in series.index],
        "values": [round(float(v), ndigits) for v in series],
    }


def _user_payload(user) -> dict:
    return {"username": user["username"], "is_admin": bool(user["is_admin"])}


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
    # Liveness only: dependency-free, so a slow upstream never gets a healthy
    # container restarted.
    return {"status": "ok"}


def _probe(check) -> dict:
    try:
        return {"ok": True, **check()}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _check_prices() -> dict:
    px = _prices()
    return {"as_of": px.index[-1].date().isoformat(), "rows": len(px), "tickers": len(px.columns)}


def _check_database() -> dict:
    with db.connect() as conn:
        conn.execute("SELECT 1").fetchone()
    return {}


@app.get("/readyz")
def readyz(response: Response):
    configured = llm_available()
    checks = {
        "prices": _probe(_check_prices),
        "database": _probe(_check_database),
        "knowledge_base": _probe(lambda: {"chunks": len(get_index().chunks)}),
        # Informational, never fatal: the chat degrades to extractive without a key.
        "llm": {"ok": True, "configured": configured,
                "mode": "gemini" if configured else "extractive"},
    }
    ready = all(c["ok"] for c in checks.values())
    if not ready:
        response.status_code = 503
    return {"ready": ready, "checks": checks}


@app.get("/metrics")
def prometheus_metrics():
    return Response(content=metrics.prometheus(), media_type="text/plain; version=0.0.4")


@app.get("/metrics.json")
def metrics_json():
    return metrics.snapshot()


@app.get("/api/tickers")
def tickers():
    return [{"ticker": t, "name": n} for t, n in TICKERS.items()]


@app.get("/api/market")
def market():
    px = _prices()
    return {
        "ranges": list(RANGES),
        "as_of": px.index[-1].date().isoformat(),
        "funds": period_returns(px),
    }


@app.get("/api/prices/{ticker}")
def prices(ticker: str, days: int = Query(365, ge=2, le=20000)):
    ticker = _require_ticker(ticker)
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
    ticker = _require_ticker(ticker)
    px = _prices()[ticker].dropna()
    start = px.index[-1] - pd.DateOffset(years=years)
    window = px[px.index >= start]
    if len(window) < 2:
        raise HTTPException(
            status_code=422,
            detail=f"{ticker} data only goes back to {px.index[0].date()}",
        )
    curve = _downsample((window / window.iloc[0]) * amount)
    final = float(curve.iloc[-1])
    return {
        "ticker": ticker,
        "amount": amount,
        "start": window.index[0].date().isoformat(),
        "end": window.index[-1].date().isoformat(),
        "final_value": round(final, 2),
        "gain": round(final - amount, 2),
        "multiple": round(final / amount, 2),
        "cagr": round(annualized_return(window) * 100, 2),
        "curve": _series(curve, ndigits=2),
    }


BENCHMARK = "SPY"


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

    # Benchmark over the portfolio's actual (clipped) window, so it's comparable.
    benchmark = None
    if list(req.allocation) != [BENCHMARK]:
        try:
            # price_start (not start) so both equity curves begin the same day.
            bench = run_backtest(
                prices, {BENCHMARK: 1.0}, start=result.price_start, end=result.end,
                risk_free_rate=rf, inflation_rate=inflation,
            )
            benchmark = {
                "ticker": BENCHMARK,
                "name": TICKERS[BENCHMARK],
                "metrics": _metrics(bench),
                "equity_curve": _series(_downsample(bench.equity_curve)),
            }
        except ValueError:
            benchmark = None  # window predates SPY; skip rather than fail

    return {
        "metrics": _metrics(result),
        "benchmark": benchmark,
        "inflation_estimated": inflation_estimated,
        "equity_curve": _series(_downsample(result.equity_curve)),
        "drawdown": _series(_downsample(result.drawdown)),
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
    return _user_payload(user)


@app.post("/api/auth/login")
def login(creds: Credentials, response: Response):
    row = db.get_user_by_name(creds.username)
    if row is None or not verify_password(creds.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    set_session_cookie(response, row["id"])
    return _user_payload(row)


@app.post("/api/auth/logout")
def logout(response: Response):
    clear_session_cookie(response)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict | None = Depends(current_user)):
    return {"user": _user_payload(user) if user else None}


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
    symbol = _require_symbol(symbol)
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
    entry = stock_catalog().get(symbol, {})
    payload["name"] = entry.get("name") or TICKERS.get(symbol, symbol)
    payload["sector"] = entry.get("sector", "")
    payload["ranges"] = list(STOCK_RANGES)
    metrics.inc("stock_history_total", {"range": range.upper()})
    return payload


@app.get("/api/stocks/{symbol}/news")
def stock_news_feed(symbol: str, limit: int = Query(8, ge=1, le=20)):
    symbol = _require_symbol(symbol)
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
    try:
        return get_movers()
    except Exception as exc:
        logger.warning("Movers failed: %s", exc)
        raise HTTPException(status_code=503, detail="Quote source unavailable") from exc


@app.get("/api/index-history")
def index_history_summary(as_of: str = Query("2010-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")):
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
    symbol = _require_symbol(req.symbol, status_code=422)
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
# Each slug is served from knowledge/<slug>.md.
LEARN_ARTICLES = (
    "what-are-etfs",
    "what-are-index-funds",
    "retirement-accounts",
    "taxable-vs-tax-advantaged",
    "hysa-vs-checking",
    "money-basics",
    "what-is-trading",
    "how-leverage-works",
    "capital-gains-and-taxes",
    "odds-and-expected-value",
)


def _article_meta(slug: str) -> dict:
    text = (KNOWLEDGE_DIR / f"{slug}.md").read_text()
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
    # HTML is never cached so deploys land immediately; ?v= assets are immutable.
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if "text/html" in content_type:
        response.headers["Cache-Control"] = "no-cache"
    elif "v=" in request.url.query:
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


# ---------------------------------------------------------------------------
# Frontend routes
#
# Two surfaces, deliberately separate: landing.html is the front door for people
# who have never seen the tool, index.html is the app itself. Real paths (not
# hash fragments) so each view is a distinct, linkable, crawlable URL.
# ---------------------------------------------------------------------------
STATIC_DIR = Path(__file__).parent / "static"

# Views owned by the app shell. Kept in sync with VIEWS in static/app.js.
APP_VIEWS = ("markets", "stocks", "backtest", "learn", "assistant", "about")


def _page(name: str) -> FileResponse:
    return FileResponse(STATIC_DIR / name, headers={"Cache-Control": "no-cache"})


if STATIC_DIR.exists():
    @app.get("/", include_in_schema=False)
    def landing():
        return _page("landing.html")

    @app.get("/app", include_in_schema=False)
    def app_root():
        return RedirectResponse("/markets", status_code=307)

    # One route per view, plus /learn/<slug> for individual articles.
    for _view in APP_VIEWS:
        app.get(f"/{_view}", include_in_schema=False)(lambda: _page("index.html"))
        app.get(f"/{_view}/{{slug}}", include_in_schema=False)(lambda slug: _page("index.html"))

    # Assets last so the named routes above win.
    app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
