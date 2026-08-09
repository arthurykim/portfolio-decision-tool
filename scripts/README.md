# `scripts/` — one-off and scheduled maintenance jobs

Nothing here is imported by the app. These are things you *run*, either by hand
or on a schedule, that produce data the app then reads.

Each has a Taskfile wrapper; prefer that over calling Python directly, since the
wrapper uses the project venv.

| Script | Task | When you run it |
|---|---|---|
| `refresh_market.py` | `task refresh` | Refreshes price data and writes `data/market_snapshot.json`. **Runs hourly in CI** (`.github/workflows/market-refresh.yml`) — you rarely run it by hand. |
| `build_vectors.py` | `task vectors:build` | Chunks `knowledge/`, embeds it, loads it into Milvus. Run after editing knowledge files or changing `CHUNK_STRATEGY` / `EMBED_MODEL`. Needs Milvus up (`task vectors:up`). |
| `build_index_history.py` | `task index:history` | Rebuilds `data/sp500_history.json` — point-in-time S&P 500 membership, replayed backward from Wikipedia's add/remove log. Fixes survivorship bias in backtests. Run rarely. |
| `create_admin.py` | `task admin` | Creates or promotes an admin user. Credentials come from `ADMIN_USER` / `ADMIN_PASS` env vars so nothing secret lands in the repo. Also resets the password if the user exists. |
| `screenshots.py` | — | Captures the README screenshots via Playwright against a locally running server (`task dev`). Development tooling, not shipped. |

## Outputs

These write into `data/`, which is committed:

- `data/market_snapshot.json` ← `refresh_market.py`
- `data/sp500_history.json` ← `build_index_history.py`

`build_vectors.py` writes to Milvus, not to disk — its output lives in the
container volume and is rebuilt on demand.

## Adding a script

Give it a module docstring with a runnable example (the existing ones all do),
and add a Taskfile entry so it is discoverable via `task --list`.
