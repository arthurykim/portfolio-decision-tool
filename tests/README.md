# `tests/` — what is covered and what it costs to run

```bash
task test                # the default suite: fast, hermetic, no services
task test:integration    # live Milvus required (see below)
```

The default suite is **hermetic**: no network, no API key, no Docker. That is a
deliberate constraint — anything needing a live service goes in
`tests/integration/` behind the `integration` marker, which `pytest.ini`
deselects by default.

## Shared setup

| File | What it does |
|---|---|
| `conftest.py` | Points `DB_PATH` at a temp directory so tests never touch `db/app.db`, and synthesises a deterministic parquet price cache for the 13 supported tickers when none exists. This is why the suite runs without network access. Also defines the `--stock` / `--live` options below. |
| `fake_yahoo.py` | An offline stand-in for `yf.download` and `yf.Ticker(...).news`, returning frames shaped like yfinance 1.x's (MultiIndex columns, tz-aware intraday index). Seeded per symbol, and respects IPO dates. |

## Unit and API tests

| File | Covers |
|---|---|
| `test_api.py` | Every `/api/*` endpoint through FastAPI's `TestClient` — status codes, payload shape, validation errors. |
| `test_auth.py` | Password hashing, session cookies, `require_user` / `require_admin` guards. |
| `test_backtest.py` | The backtest engine against synthetic prices — returns, drawdown, rebalancing. |
| `test_data.py` | Price loading, caching, and the ticker catalog. |
| `test_env.py` | `.env` parsing and precedence over the real environment. |
| `test_observability.py` | Metrics counters, histogram buckets, request-id propagation, Prometheus rendering. |
| `test_rag.py` | BM25 scoring, prompt assembly, and the extractive fallback when no LLM is configured. |
| `test_chunking.py` | Every chunking strategy plus deduplication. Pure Python — no model download. |
| `test_retrieval_modes.py` | Mode selection, RRF fusion, and the guarantee that a missing Milvus degrades to BM25. **The vector store is stubbed** — this tests the fallback logic, not Milvus. |
| `test_stocks.py` | The stock endpoints (history for every range, news, quotes, watchlist) and, for the curated funds, prices/growth/backtest, **for whichever symbols you choose**. See below. |
| `test_index_history.py` | Point-in-time index reconstruction. Skips when `data/sp500_history.json` has not been generated, so CI stays hermetic. |

## Testing a specific stock

```bash
task test:stock                    # the default set: AAPL, RDDT, SPY, SPX
task test:stock -- NVDA TSLA       # your symbols, offline (synthetic prices)
task test:stock:live -- NVDA       # your symbols, real Yahoo Finance data
pytest tests/test_stocks.py --stock NVDA --stock TSLA [--live]
```

No checkout? Actions tab → **stock check** → *Run workflow*, and enter the
symbols.

Every check asserts something that has to hold for *any* stock: the payload
shape both frontends read, stats that agree with the points they summarise, a
window that matches the requested range, and the Yahoo symbol and
period/interval the backend asked for. Because nothing depends on particular
prices, the same checks run against both data sources:

- **Offline** (default, and what CI runs on every PR): proves the backend's
  handling of the symbol (catalog lookup, Yahoo spelling, parsing, stats) against
  `fake_yahoo.py`. Fast and hermetic, but the prices are synthetic.
- **`--live`**: the same assertions against real data, which answers "does NVDA
  work end to end right now?" If Yahoo is unreachable the run stops with an
  error; it never passes on nothing.

The defaults each take a different path through the backend: an S&P 500
stock, a recent IPO (short history), a curated fund (also served by
`/api/prices`, `/api/growth`, `/api/backtest`), and an index Yahoo spells
differently (`SPX` is `^GSPC`). A symbol outside the catalog fails
`test_symbol_is_served` once, explaining how to add it, and its other tests skip.

## `integration/`

| File | Covers |
|---|---|
| `test_vectorstore_milvus.py` | The real embeddings → Milvus → RRF chain. Builds the actual knowledge base into a throwaway collection, embeds with the real sentence-transformer model, and queries it. |

Requires:

```bash
task vectors:up          # single Milvus container, healthy in seconds
task test:integration
```

It **skips** rather than fails when Milvus or `sentence-transformers` is absent,
so a developer without Docker running still gets a clean result. In CI it runs
in its own workflow (`.github/workflows/integration.yml`) — kept out of `ci.yml`
because installing torch and downloading the model takes minutes.

## Conventions

- A test that needs an external service gets `pytestmark = pytest.mark.integration`
  and lives in `integration/`. Nothing else may reach the network.
- Prefer asserting on behaviour that would actually break a user. `test_retrieval_modes.py`
  and the integration file are deliberately split along this line: one proves the
  fallback *logic* is right, the other proves the real thing *works*.
