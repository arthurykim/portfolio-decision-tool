# Proposal: repo structure

**Status:** proposed, not accepted
**Scope:** layout only — no behaviour changes

This is a proposal for discussion, not a decision. It is written down because
the repo has reached the size where the flat layout has started costing real
bugs, and because a new engineer is joining and will otherwise learn the current
shape as if it were intentional.

## The problem, concretely

Ten application modules sit at the repository root, alongside config files,
two frontends, and four support directories:

```
main.py  data.py  backtest.py  rag.py  embeddings.py  vectorstore.py
db.py  auth.py  observability.py  env.py
```

Three specific costs, all observed rather than hypothetical:

**1. It has already shipped a production bug.** The Dockerfile could not say
"copy the application"; it had to name modules one at a time:

```dockerfile
COPY data.py backtest.py rag.py db.py auth.py main.py ./
```

That list went stale. `env.py` and `observability.py` are imported at the top of
`main.py` and were never in it, so the image built successfully and the container
died on startup with `ModuleNotFoundError`. Fixed in #8 with a `*.py` glob, but
the glob is a workaround for the layout, not a solution. With a package it is
`COPY app/ app/` and the failure mode does not exist.

**2. Nine files manipulate `sys.path` to import the app.** Every script in
`eval/` and `scripts/` opens with:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

This is import machinery hand-rolled because there is no installable package. It
also forces `# noqa: E402` on the imports that follow, which is why `ruff.toml`
carries per-file E402 exemptions.

**3. There is no boundary between layers.** `main.py` (643 lines) can import
anything. Nothing distinguishes "HTTP layer" from "retrieval internals", so
nothing prevents them coupling — and nothing tells a newcomer which direction
dependencies are supposed to flow.

## Blast radius

Measured, not estimated:

| | count |
|---|---|
| Tracked `.py` files | 34 |
| Import lines to rewrite | 56 |
| `sys.path` hacks to delete | 9 |
| Non-Python files referencing module paths | 7 |

The 7 non-Python files: `Dockerfile`, `Taskfile.yml`, `ruff.toml`,
`.github/workflows/integration.yml`, `static/app.js`, `README.md`,
`eval/README.md`.

This is a large diff but a shallow one. It is almost entirely mechanical, and
the 128-test suite plus the container boot check in CI cover the result.

## Proposed structure

```
portfolio-decision-tool/
├── app/                     # the application, one importable package
│   ├── __init__.py
│   ├── main.py              # FastAPI app + routes
│   ├── core/                # cross-cutting, depended on by everything
│   │   ├── env.py
│   │   └── observability.py
│   ├── market/              # prices and analysis
│   │   ├── data.py
│   │   └── backtest.py
│   ├── retrieval/           # the RAG half
│   │   ├── rag.py
│   │   ├── embeddings.py
│   │   └── vectorstore.py
│   └── storage/             # persistence and identity
│       ├── db.py
│       └── auth.py
├── knowledge/               # unchanged — RAG corpus
├── frontend/                # unchanged — React client
├── static/                  # unchanged — deployed vanilla frontend
├── eval/  scripts/  tests/  # unchanged, minus the sys.path hacks
├── deploy/  docs/
└── pyproject.toml           # new: makes `app` installable
```

Dependencies flow one way: `main` → `market`/`retrieval`/`storage` → `core`.
Stating that is most of the value; the directories just make violations visible.

### `pyproject.toml`

The piece that retires the `sys.path` hacks. `pip install -e .` in `task setup`,
after which `from app.retrieval import rag` works from anywhere — `eval/`,
`scripts/`, `tests/`, and the container alike, with no path surgery and no
`E402` exemptions.

## Phasing

Deliberately split, so no single PR is both large and risky.

**Phase 1 — move into `app/`, keep it flat** *(recommended first step)*
`git mv` the ten modules into `app/`, add `__init__.py`, rewrite 56 imports,
update the 7 config references. No subpackages yet. Fully mechanical; the diff
reads as a rename.

**Phase 2 — `pyproject.toml` + delete the `sys.path` hacks**
Editable install, remove 9 hacks and the `E402` exemptions they forced.

**Phase 3 — introduce `core/`, `market/`, `retrieval/`, `storage/`**
Another pure move, but now the layering is real and reviewable on its own.

**Phase 4 — optional: split `main.py` into routers**
643 lines and 22 routes is manageable but not obviously so at 40 routes. Only
worth doing if the file keeps growing. Not recommended yet.

Phases 1–3 are one afternoon and could be a single day's work. Phase 4 is a
genuine refactor and should wait for a reason.

## What this does not address

**The two frontends.** `static/` is deployed; `frontend/` is the React rewrite;
they overlap in what they render, and the landing page (#9) added ~1,360 lines to
`static/`. That is a product decision, not a layout one, and it wants its own
discussion. Listed here only so it is not mistaken for an oversight.

## Recommendation

Do Phase 1 and 2 together, soon, and while no long-lived branches are open —
they are mechanical and they retire a class of bug that has already cost us once.
Do Phase 3 when someone next has cause to touch the retrieval or storage code.
Leave Phase 4 alone.

Not doing this is also a defensible answer for a repo this size. What is not
defensible is the current state being undocumented, which this file fixes
regardless of what gets decided.
