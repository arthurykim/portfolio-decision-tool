# `eval/` — measuring whether retrieval and answers are any good

Every change to chunking, tokenizing, or retrieval mode is a guess until it is
scored. This folder is the scoreboard.

Two kinds of evaluation live here, and the difference matters:

- **Retrieval evaluation** is offline and free. It asks "did we hand the model
  the right passage?" — pure local computation, no API key, no cost. Run these
  constantly.
- **Answer evaluation** (RAGAS) calls Gemini to judge the generated text. It
  needs `GOOGLE_API_KEY` and costs money per run. Run it before you ship.

## Files

### The dataset
| File | What it is |
|---|---|
| `golden_qa.jsonl` | The golden set: questions paired with the knowledge file that should answer them. Every script here scores against this. Adding a question is how you extend coverage. |

### Offline scoring (no API key)
| File | What it does |
|---|---|
| `retrieval_eval.py` | Scores BM25 on the golden set — recall@1, recall@3, MRR. The baseline number. `task eval:retrieval` |
| `chunking_sweep.py` | Runs *every* strategy in `rag.CHUNKERS` over the golden set and prints a side-by-side table. The fast loop for chunking experiments. `task eval:chunking` |
| `retrieval_modes.py` | Compares `bm25` vs `dense` vs `hybrid`. The experiment the embedding work exists to settle. **Needs Milvus running plus `task vectors:build`.** `task eval:modes` |

### LLM-judged scoring (needs `GOOGLE_API_KEY`)
| File | What it does |
|---|---|
| `ragas_eval.py` | RAGAS metrics on the chat assistant: faithfulness, context precision, context recall. `task eval` |
| `requirements-eval.txt` | Pinned deps for the above. Installed into a **separate** `.venv-eval` because RAGAS pins an older LangChain than the app uses — do not merge these into `requirements.txt`. |

### Run history
| File | What it does |
|---|---|
| `history.py` | Append-only run log. Stamps each result with git commit + working-tree state, so a score is traceable to the code that produced it. |
| `history_report.py` | Renders `history.jsonl` as a trend. `task eval:history` |
| `history.jsonl` | The log itself, one JSON object per line, newest last. Committed on purpose — the trend is the artifact. |

### Cached results
`chunking_results.json`, `retrieval_results.json`, `mode_results.json` are the
latest output of their respective scripts, kept so the README and docs can cite
numbers without a rerun.

## Typical loop

```bash
task eval:retrieval      # baseline
# ...edit chunking in rag.py...
task eval:chunking       # compare all strategies
task eval:history        # did it actually help?
```

A single run tells you the current score. The history tells you whether a change
helped — which is the only question that matters when tuning.
