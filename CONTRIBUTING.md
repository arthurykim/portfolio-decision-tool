# Contributing

Start here if you have just joined the project. The [README](README.md) explains
what the tool *is*; this explains how to work on it.

## Day one

```bash
task setup                 # venv + Python deps
cp .env.example .env       # optional: add GOOGLE_API_KEY for the AI assistant
task dev                   # http://localhost:8000
```

The first request downloads ~10 ticker histories from Yahoo Finance (10–20 s),
then caches to parquet. Everything after that is fast and offline.

Nothing above needs an API key, Docker, or network access at test time. If a
change of yours starts requiring one of those to run the default test suite,
that is a signal something has been wired too tightly — see
[`tests/README.md`](tests/README.md).

Then run the full check once, so you know what green looks like before you
change anything:

```bash
task check                 # lint + config validation + 128 tests
```

`task --list` shows every command. There is a task for almost everything; prefer
it over remembering raw invocations.

## The mental model

Read these four things, in this order. It is about an hour and it covers ~90% of
what the codebase does:

1. **[README.md](README.md) → Architecture** — the request paths, one screen.
2. **[docs/RETRIEVAL.md](docs/RETRIEVAL.md)** — how the RAG pipeline works. This
   is the least guessable part of the repo.
3. **[knowledge/README.md](knowledge/README.md)** — why the markdown files are
   shaped the way they are. Heading structure is not cosmetic here: every `##`
   becomes a standalone retrieval unit.
4. **[eval/README.md](eval/README.md)** — how retrieval quality is measured. The
   project treats "did this help?" as a question with a number attached.

## Making a change

```bash
git checkout -b <type>/<short-description>    # feat/ fix/ docs/ chore/ test/ ci/
# ... work ...
task check
git push -u origin <branch>
gh pr create
```

Branch naming follows the prefixes above — it is what the existing branches use.

**Commits** are plain and incremental. Write what changed and why; skip
ceremony. If a commit fixes something subtle, the *why* belongs in the message,
not only in the diff.

**Pull requests** carry the reasoning. The existing PRs on this repo are the
house style and worth skimming: they state the problem, the shape of the fix,
what was verified, and — importantly — what was *not* verified. Claiming more
verification than you did is the one thing that will get a PR sent back.

## What CI enforces

Every pull request runs, automatically:

| Job | What it checks | Roughly |
|---|---|---|
| `lint` | `ruff check` over the repo | 10s |
| `test` | 128 hermetic Python tests | 2m |
| `frontend` | React typecheck, tests, build | 25s |
| `docker` | Image builds **and the container boots** (`/healthz`) | 2m |
| `milvus` | 9 integration tests against a real Milvus | 3m |

Two of these exist because of bugs that got through:

- **`docker` boots the container** because `docker build` alone once passed on an
  image that died instantly on startup — a module was missing from the
  Dockerfile's copy list. Building proves the file parses, not that it runs.
- **`milvus` runs on every PR**, not just retrieval-file changes, because a path
  filter cannot see indirect breakage. A `data.py` edit or a dependency bump can
  break the retrieval path without touching anything on a filter list.

`main` is not currently branch-protected, so these are advisory. Treat them as
blocking anyway.

## Conventions worth knowing

**Degradation over failure.** Optional dependencies degrade, they do not raise.
No Milvus, no `sentence-transformers`, no `GOOGLE_API_KEY` — the app still
starts, the tests still pass, retrieval falls back to BM25, chat falls back to
extractive answers. If you add an optional dependency, it follows this rule.

**Comments explain *why*.** The codebase is unusually well commented, and
specifically about non-obvious decisions — why the primary key is read as
`h["uid"]` and not `h["id"]`, why the dedup threshold is 0.9, why `E402` is
exempted in `main.py`. Match that. A comment restating the code is noise; a
comment recording a decision saves the next person an afternoon.

**Numbers in docs must be real.** Published metrics are measured, not
remembered. `eval/history.jsonl` keeps the trail. If you change chunking or
retrieval, re-run `task eval:retrieval` and update what the docs claim.

**Two frontends.** `static/` is deployed; `frontend/` is the React rewrite. Know
which one your change affects. See the README section on this.

## Where things are

Each major folder has its own README:
[`eval/`](eval/README.md) · [`knowledge/`](knowledge/README.md) ·
[`scripts/`](scripts/README.md) · [`tests/`](tests/README.md) ·
[`frontend/`](frontend/README.md)

## Getting unstuck

- **Something is stale or contradicts the code** — the docs are wrong, not you.
  Fix them in the same PR; that is always in scope.
- **A test needs a live service** — it belongs in `tests/integration/` behind the
  `integration` marker.
- **Prices look wrong locally** — `rm -rf cache/` and let it re-download.
- **The knowledge base changed but the assistant did not notice** — the dense
  index is built, not live. Re-run `task vectors:build`.
