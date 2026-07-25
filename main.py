"""Portfolio Decision Tool — FastAPI backend.

Serves the JSON API under /api/* and the static frontend at /.
Run locally:  uvicorn main:app --reload
"""
import logging
import threading
import time
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from backtest import run_backtest
from data import TICKERS, get_quotes, load_universe
from rag import answer as rag_answer

logger = logging.getLogger("uvicorn.error")

app = FastAPI(
    title="Portfolio Decision Tool API",
    version="1.0.0",
    description="Backtest capital allocations against real historical market data.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # public read-only API; tighten if auth is ever added
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-process caches. Price history is already cached on disk by data.py;
# quotes get a short TTL memory cache so the UI can poll cheaply.
# ---------------------------------------------------------------------------
_quote_cache: dict = {"data": None, "ts": 0.0}
_QUOTE_TTL = 300  # seconds
_lock = threading.Lock()


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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/api/tickers")
def tickers():
    return [{"ticker": t, "name": n} for t, n in TICKERS.items()]


@app.get("/api/quotes")
def quotes():
    now = time.time()
    with _lock:
        if _quote_cache["data"] is not None and now - _quote_cache["ts"] < _QUOTE_TTL:
            return _quote_cache["data"]
    try:
        data = get_quotes()
    except Exception as exc:
        logger.warning("Quote fetch failed: %s", exc)
        with _lock:
            if _quote_cache["data"] is not None:
                return _quote_cache["data"]  # serve stale over erroring
        raise HTTPException(status_code=503, detail="Quote source unavailable")
    with _lock:
        _quote_cache.update(data=data, ts=now)
    return data


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


@app.post("/api/backtest")
def backtest(req: BacktestRequest):
    try:
        result = run_backtest(_prices(), req.allocation, start=req.start, end=req.end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Downsample the curve for the wire: weekly points keep charts snappy
    # without visibly changing the shape.
    equity = result.equity_curve
    if len(equity) > 1500:
        equity = equity.resample("W-FRI").last().dropna()
    drawdown = equity / equity.cummax() - 1

    return {
        "metrics": {
            "start": result.start.date().isoformat(),
            "end": result.end.date().isoformat(),
            "total_return": result.total_return,
            "cagr": result.cagr,
            "volatility": result.volatility,
            "sharpe": result.sharpe,
            "max_drawdown": result.max_drawdown,
        },
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
        return rag_answer(req.message, [t.model_dump() for t in req.history])
    except Exception as exc:
        logger.warning("Chat failed: %s", exc)
        raise HTTPException(status_code=500, detail="Chat unavailable")


# Static frontend last so /api/* wins routing.
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
