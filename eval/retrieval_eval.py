"""Score retrieval against the golden set: recall@1, recall@3, MRR. Offline.

    python eval/retrieval_eval.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env import load_env  # noqa: E402

load_env()

import history  # noqa: E402
from scoring import K, load_cases, numeric, score  # noqa: E402

from rag import chunk_strategy, get_index, retrieve  # noqa: E402

RESULTS = Path(__file__).parent / "retrieval_results.json"


def main() -> None:
    cases = load_cases()
    result = score(cases, lambda q: [p["source"] for p in retrieve(q, k=K)])
    rows, metrics = result["cases"], numeric(result)
    n = len(cases)
    summary = {"questions": n, **metrics}
    RESULTS.write_text(json.dumps({"summary": summary, "cases": rows}, indent=2) + "\n")

    strategy = chunk_strategy()
    index = get_index()
    deltas, prior = {}, None
    if history.enabled():
        # Compare against the last run of the same strategy, not just the last
        # run of anything — otherwise a strategy sweep looks like a regression.
        prior = history.previous("retrieval", {"strategy": strategy})
        deltas = history.compare(metrics, prior)
        history.record(
            "retrieval", metrics,
            config={"strategy": strategy, "k": K},
            corpus={"questions": n, "chunks": len(index.chunks),
                    "avg_tokens": round(index.avgdl, 1)},
        )

    print(f"Retrieval over {n} golden questions (BM25, no API calls)\n")
    print(f"  recall@1   {summary['recall_at_1']:.1%}  correct file ranked first")
    print(f"  recall@{K}   {summary[f'recall_at_{K}']:.1%}  correct file in top {K}")
    print(f"  MRR        {summary['mrr']:.3f}")

    misses = [r for r in rows if r["rank"] != 1]
    if misses:
        print(f"\n{len(misses)} question(s) where the top hit was not the expected file:")
        for m in misses:
            got = m["retrieved"][0] if m["retrieved"] else "nothing"
            print(f"  · {m['question'][:58]}")
            print(f"      expected {m['expected']}, got {got} (rank {m['rank'] or 'miss'})")

    if deltas:
        print(history.format_deltas(deltas, prior))
    print(f"\nPer-question detail written to {RESULTS.name}")
    if history.enabled():
        print(f"Run appended to {history.HISTORY.name} ({len(history.load('retrieval'))} total)")


if __name__ == "__main__":
    main()
