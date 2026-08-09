"""Measure BM25 retrieval quality against the golden set.

Runs fully offline — no API key, no cost — because retrieval is local. It scores
whether the correct knowledge-base file is ranked first (recall@1), appears in
the top 3 (recall@3), and how high it lands on average (MRR).

    python eval/retrieval_eval.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env import load_env  # noqa: E402

load_env()

import history  # noqa: E402

from rag import DEFAULT_CHUNKER, get_index, retrieve  # noqa: E402

GOLDEN = Path(__file__).parent / "golden_qa.jsonl"
RESULTS = Path(__file__).parent / "retrieval_results.json"
K = 3


def main() -> None:
    cases = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    rows, hits_at_1, hits_at_k, reciprocal_ranks = [], 0, 0, 0.0

    for case in cases:
        expected = case["expected_source"]
        ranked = [p["source"] for p in retrieve(case["question"], k=K)]
        rank = ranked.index(expected) + 1 if expected in ranked else 0

        hits_at_1 += rank == 1
        hits_at_k += rank > 0
        reciprocal_ranks += 1 / rank if rank else 0.0
        rows.append({
            "question": case["question"],
            "expected_source": expected,
            "retrieved": ranked,
            "rank": rank,
        })

    n = len(cases)
    summary = {
        "questions": n,
        "recall_at_1": round(hits_at_1 / n, 3),
        f"recall_at_{K}": round(hits_at_k / n, 3),
        "mrr": round(reciprocal_ranks / n, 3),
    }
    RESULTS.write_text(json.dumps({"summary": summary, "cases": rows}, indent=2) + "\n")

    strategy = os.environ.get("CHUNK_STRATEGY") or DEFAULT_CHUNKER
    index = get_index()
    deltas = {}
    if history.enabled():
        # Compare against the last run of the same strategy, not just the last
        # run of anything — otherwise a strategy sweep looks like a regression.
        prior = history.previous("retrieval", {"strategy": strategy})
        metrics = {k: v for k, v in summary.items() if k != "questions"}
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
            print(f"      expected {m['expected_source']}, got {got} (rank {m['rank'] or 'miss'})")

    if deltas:
        print(history.format_deltas(deltas, history.load("retrieval", {"strategy": strategy})[-2]))
    print(f"\nPer-question detail written to {RESULTS.name}")
    if history.enabled():
        print(f"Run appended to {history.HISTORY.name} ({len(history.load('retrieval'))} total)")


if __name__ == "__main__":
    main()
