# Portfolio Decision Tool

[![ci](https://github.com/arthurykim/portfolio-decision-tool/actions/workflows/ci.yml/badge.svg)](https://github.com/arthurykim/portfolio-decision-tool/actions/workflows/ci.yml)
[![market refresh](https://github.com/arthurykim/portfolio-decision-tool/actions/workflows/market-refresh.yml/badge.svg)](https://github.com/arthurykim/portfolio-decision-tool/actions/workflows/market-refresh.yml)

Track major index funds, backtest allocations against decades of real market
data, and learn the concepts as you go — in one self-contained web app.

**Educational tool only. Nothing here is investment advice.**

## Features

- **Market dashboard** — live-ish prices and returns for 11 major ETFs (SPY,
  VOO, QQQ, VTI, VXUS, AGG, IEF, TLT, GLD, VNQ, BIL) across 1D / 1W / 1M /
  YTD / 1Y / 5Y / All ranges, with sparklines and an interactive price chart.
  A GitHub Actions cron refreshes a committed market snapshot every hour
  during US trading hours.
- **Today's movers** — top 5 risers and fallers across the S&P 500 by 1-day
  change, computed live from the full catalog.
- **Stocks** — paginated, searchable S&P 500 catalog (503 constituents across
  11 pages) plus a curated recent-tech-IPO strip, all with live quotes. Sign in
  to pin stocks to a personal watchlist.
- **Learn** — original explainer articles (What are ETFs? · What are index
  funds? · Retirement accounts: 401(k)/Traditional IRA/Roth IRA · Taxable vs.
  tax-advantaged), reachable from a nav dropdown or tile grid, plus a
  "where to start" panel linking to major brokerages.
- **Accounts** — lightweight self-hosted auth: scrypt-hashed passwords,
  HMAC-signed HttpOnly session cookies, SQLite storage, zero external
  dependencies. The first registered user becomes the site admin and can edit
  the About page in place.
- **"What if I had invested…"** — hypothetical lump-sum calculator: $1,000–5,000
  into any supported fund 1–30 years ago, with the resulting growth curve,
  gain, and CAGR.
- **Backtest lab** — weight any mix of the 11 funds (presets: 60/40,
  Three-Fund, All Weather, Golden Butterfly), pick a date window, and get an
  equity curve **overlaid against the S&P 500**, a drawdown chart, and a full
  risk panel: CAGR, **real (inflation-adjusted) CAGR**, volatility, **Sharpe
  against the actual T-bill rate** (derived from BIL, not assumed zero),
  **Sortino**, **Calmar**, max drawdown, and **longest time underwater**.
  Every run is also summarized in plain English for non-finance readers.
- **RAG chat assistant** — asks-anything box over a curated finance knowledge
  base (metrics, asset classes, strategies, market history) using BM25
  retrieval. With an `ANTHROPIC_API_KEY` it generates grounded answers with
  Claude; without one it falls back to returning the best-matching passage.
  Answer quality is measured with a [RAGAS](https://docs.ragas.io) harness.

## Architecture

```
┌─────────────────────────── one container ────────────────────────────┐
│  FastAPI (main.py)                                                   │
│  ├── /api/market         period returns for the dashboard            │
│  ├── /api/prices/:t      daily close history                         │
│  ├── /api/growth         hypothetical lump-sum calculator            │
│  ├── /api/backtest       allocation backtest (backtest.py)           │
│  ├── /api/chat           RAG assistant (rag.py + knowledge/*.md)     │
│  ├── /api/stocks/quotes  quotes for catalog symbols                  │
│  ├── /api/auth/*         register / login / logout (auth.py)         │
│  ├── /api/watchlist      per-user pinned stocks (db.py, SQLite)      │
│  ├── /api/about          editable site content (admin)               │
│  └── /                   static frontend (vanilla JS, SVG charts)    │
│                                                                      │
│  data.py — yfinance download → parquet cache (hourly TTL)            │
└──────────────────────────────────────────────────────────────────────┘
```

No build step, no frontend framework, no external services: prices cache to
parquet, users and watchlists live in a single SQLite file, the UI is one
static page, and the whole thing ships as one Docker image.

## Quickstart

With [Task](https://taskfile.dev) (`brew install go-task`):

```bash
task setup    # create venv, install deps
task dev      # run at http://localhost:8000
task test     # run the test suite
```

Without Task:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest httpx
.venv/bin/uvicorn main:app --reload   # http://localhost:8000
```

Docker:

```bash
task docker:up          # or: docker compose up --build
```

The first request downloads ~10 ticker histories from Yahoo Finance (10–20 s),
then everything is cached and auto-refreshed hourly.

### Enable the AI assistant (optional)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
task dev
```

Without a key the chat still answers from the knowledge base in extractive mode.

## Testing & evaluation

```bash
task test     # unit + API tests; hermetic (synthetic data seeded if no cache)
task eval     # RAGAS metrics for the chat assistant (needs ANTHROPIC_API_KEY)
```

The RAGAS harness scores faithfulness, context precision, and context recall
against a 12-question golden set (`eval/golden_qa.jsonl`) and writes
per-case results to `eval/results.json`.

## Deployment

One container, any host. Scripted path for **AWS App Runner** and a documented
alternative for **Azure Container Apps** — see [deploy/DEPLOY.md](deploy/DEPLOY.md).

```bash
task deploy:aws       # ECR push + App Runner create/redeploy
```

## Data & methodology

- Prices are Yahoo Finance adjusted daily closes (dividends included via
  adjustment), delayed ~15 minutes.
- Backtests assume daily rebalancing and no fees, taxes, or slippage. Daily
  rebalancing slightly overstates the rebalancing bonus versus the monthly or
  quarterly cadence most investors actually use.
- Sharpe and Sortino subtract a real risk-free rate derived from BIL (1–3 month
  T-bills) over the same window, not an assumed 0%. Windows that predate BIL's
  2007 inception fall back to 0%.
- Real returns use BLS CPI-U annual averages (`data/cpi.json`). Values are
  verified through the year recorded in that file; later periods are estimated,
  and the UI labels results as such.
- Windows clip to the overlapping history of the selected tickers (e.g. VXUS
  data starts in 2011).
- **Known limitation — survivorship bias:** the stock catalog is the *current*
  S&P 500 membership, so companies that were delisted or went bankrupt are
  absent. Any analysis built on today's constituents is biased upward relative
  to what an investor would actually have experienced.
- `data/market_snapshot.json` is refreshed hourly by CI and doubles as a
  public, versioned record of the dashboard numbers.

## Repo map

| Path | What it is |
|---|---|
| `main.py` | FastAPI app: API routes + static serving |
| `data.py` | Price download, parquet cache, period returns |
| `backtest.py` | Backtest engine and metrics |
| `rag.py` | BM25 index + optional Claude generation |
| `knowledge/` | Finance knowledge base + Learn articles (9 markdown files) |
| `static/` | Frontend (HTML/CSS/JS, no framework) |
| `db.py` / `auth.py` | SQLite persistence + stdlib session auth |
| `tests/` | 57 pytest tests, hermetic via synthetic fixtures |
| `eval/` | RAGAS golden set + evaluation script |
| `scripts/refresh_market.py` | Hourly snapshot generator (CI cron) |
| `deploy/` | App Runner script + deployment docs |
