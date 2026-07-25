"""Portfolio Decision Tool — FastAPI backend.

Serves the JSON API under /api/* and the static frontend at /.
Run locally:  uvicorn main:app --reload
"""
import logging
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from backtest import run_backtest
from data import RANGES, TICKERS, load_universe, period_returns
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
    amount: float = Query(..., ge=100, le=1_000_000),
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
