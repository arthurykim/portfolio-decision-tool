# `tests/` — what is covered and what it costs to run

```bash
task test                # the default suite: fast, hermetic, no services
task test:cov            # the same suite, with a coverage report and floor
task test:integration    # live Milvus required (see below)
```

The default suite is **hermetic**: no network, no API key, no Docker. That is a
deliberate constraint — anything needing a live service goes in
`tests/integration/` behind the `integration` marker, which `pytest.ini`
deselects by default.

## Shared setup

| File | What it does |
|---|---|
| `conftest.py` | Points `DB_PATH` at a temp directory so tests never touch `db/app.db`, and synthesises a deterministic parquet price cache for the 13 supported tickers when none exists. This is why the suite runs without network access. |

## Unit and API tests

| File | Covers |
|---|---|
| `test_api.py` | Every `/api/*` endpoint through FastAPI's `TestClient` — status codes, payload shape, validation errors. |
| `test_auth.py` | Password hashing, session cookies, `require_user` / `require_admin` guards. |
| `test_stocks_api.py` | The Stocks routes (`quotes`, `history`, `news`), watchlist pin/unpin, and Learn article lookup. Upstream data is faked — see the note on patching below. |
| `test_backtest.py` | The backtest engine against synthetic prices — returns, drawdown, rebalancing. |
| `test_data.py` | Price loading, caching, and the ticker catalog. |
| `test_env.py` | `.env` parsing and precedence over the real environment. |
| `test_observability.py` | Metrics counters, histogram buckets, request-id propagation, Prometheus rendering. |
| `test_rag.py` | BM25 scoring, prompt assembly, and the extractive fallback when no LLM is configured. |
| `test_chunking.py` | Every chunking strategy plus deduplication. Pure Python — no model download. |
| `test_retrieval_modes.py` | Mode selection, RRF fusion, and the guarantee that a missing Milvus degrades to BM25. **The vector store is stubbed** — this tests the fallback logic, not Milvus. |
| `test_index_history.py` | Point-in-time index reconstruction. Skips when `data/sp500_history.json` has not been generated, so CI stays hermetic. |

## `integration/`

| File | Covers |
|---|---|
| `test_vectorstore_milvus.py` | The real embeddings → Milvus → RRF chain. Builds the actual knowledge base into a throwaway collection, embeds with the real sentence-transformer model, and queries it. |

Requires:

```bash
task vectors:up          # etcd + MinIO + Milvus, ~1-2 min cold start
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

## Coverage

`task test:cov` reports coverage and enforces a floor set in `.coveragerc`
(currently **82%**; CI measures ~83%, local ~84%). CI runs the same thing, so a change
that adds code without tests fails the `test` job rather than quietly eroding
the suite.

Local coverage reads about a point higher than CI: a developer with a populated
`cache/` exercises more of `data.py` than CI's synthetic fixtures do. The floor
is set against the **CI** figure, since that is the one that gates merges.

The floor is a **ratchet, not a target** — when coverage rises, raise it. Do not
lower it to make a PR pass; that is the failure mode it exists to prevent.

`.coveragerc` measures by discovery (`source = .`) rather than a list of
modules, so a new module is measured the day it is added. A hand-maintained list
is what let `env.py` and `observability.py` fall out of the Dockerfile unnoticed.

Where the remaining gaps are, as of this writing:

| Module | Cover | Why |
|---|---|---|
| `data.py` | 59% | The yfinance-facing paths — quotes, history, news. Hermetic tests can only reach these through fakes, and most are not faked yet. **The biggest remaining gap.** |
| `vectorstore.py` / `embeddings.py` | 54% / 44% | Covered by `tests/integration/`, which the default run deselects. Not really untested. |

## A note on patching

`main.py` does `from data import stock_news, ...`, which binds the name onto
`main` at import time. Patching `data.stock_news` therefore leaves `main`'s
reference untouched and the test hits the network for real. Patch the name on
the module that *uses* it:

```python
monkeypatch.setattr(main, "stock_news", fake)   # correct
monkeypatch.setattr(data, "stock_news", fake)   # silently does nothing here
```
