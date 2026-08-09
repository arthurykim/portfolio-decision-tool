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
| `conftest.py` | Points `DB_PATH` at a temp directory so tests never touch `db/app.db`, and synthesises a deterministic parquet price cache for the 13 supported tickers when none exists. This is why the suite runs without network access. |

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
