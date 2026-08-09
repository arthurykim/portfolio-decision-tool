"""Compare retrieval modes — bm25 vs dense vs hybrid — on the golden set.

This is the experiment the embedding work exists to settle: does dense retrieval
actually fix the paraphrase questions BM25 misses, and does fusing the two beat
either alone? It scores the same golden questions and metrics as
retrieval_eval.py, so the numbers are directly comparable.

Needs Milvus running with the collection built:

    docker compose --profile vectors up -d
    task vectors:build
    task eval:modes

Modes whose backend is unavailable are reported as skipped rather than silently
scoring as BM25.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env import load_env  # noqa: E402

load_env()

import history  # noqa: E402

import vectorstore  # noqa: E402
from rag import DEFAULT_CHUNKER, MODES, retrieve  # noqa: E402

GOLDEN = Path(__file__).parent / "golden_qa.jsonl"
RESULTS = Path(__file__).parent / "mode_results.json"
K = 3


def score(mode: str, cases: list[dict]) -> dict:
    hits_at_1 = hits_at_k = 0
    reciprocal_ranks = 0.0
    misses = []
    for case in cases:
        expected = case["expected_source"]
        ranked = [p["source"] for p in retrieve(case["question"], k=K, mode=mode)]
        rank = ranked.index(expected) + 1 if expected in ranked else 0
        hits_at_1 += rank == 1
        hits_at_k += rank > 0
        reciprocal_ranks += 1 / rank if rank else 0.0
        if rank != 1:
            misses.append({
                "question": case["question"],
                "expected": expected,
                "got": ranked[0] if ranked else None,
                "rank": rank,
            })
    n = len(cases)
    return {
        "recall_at_1": round(hits_at_1 / n, 3),
        f"recall_at_{K}": round(hits_at_k / n, 3),
        "mrr": round(reciprocal_ranks / n, 3),
        "total_misses": sum(1 for m in misses if m["rank"] == 0),
        "misses": misses,
    }


def main() -> None:
    cases = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    strategy = os.environ.get("CHUNK_STRATEGY") or DEFAULT_CHUNKER
    dense_ok = vectorstore.available()

    results, skipped = {}, []
    for mode in MODES:
        if mode != "bm25" and not dense_ok:
            skipped.append(mode)
            continue
        results[mode] = score(mode, cases)

    RESULTS.write_text(json.dumps(
        {"questions": len(cases), "k": K, "strategy": strategy,
         "modes": results, "skipped": skipped}, indent=2,
    ) + "\n")

    print(f"Retrieval modes over {len(cases)} golden questions "
          f"(chunking: {strategy})\n")
    header = (f"{'mode':<10}{'recall@1':>10}{'recall@'+str(K):>10}"
              f"{'MRR':>8}{'total misses':>15}")
    print(header)
    print("-" * len(header))
    for mode, m in sorted(results.items(), key=lambda kv: kv[1]["mrr"], reverse=True):
        print(f"{mode:<10}{m['recall_at_1']:>9.1%}{m[f'recall_at_{K}']:>9.1%}"
              f"{m['mrr']:>8.3f}{m['total_misses']:>15}")

    if skipped:
        print(f"\nskipped {', '.join(skipped)}: {vectorstore.stats().get('reason', 'unavailable')}")
        print("  start it with:  task vectors:up && task vectors:build")

    if len(results) > 1:
        base = results["bm25"]
        print("\nvs bm25:")
        for mode, m in results.items():
            if mode == "bm25":
                continue
            d1 = m["recall_at_1"] - base["recall_at_1"]
            dm = m["mrr"] - base["mrr"]
            dmiss = m["total_misses"] - base["total_misses"]
            print(f"  {mode:<9} recall@1 {d1:+.1%}   MRR {dm:+.3f}   "
                  f"total misses {dmiss:+d}")

    if history.enabled():
        for mode, res in results.items():
            history.record(
                "retrieval_mode",
                {k: v for k, v in res.items() if isinstance(v, (int, float))},
                config={"strategy": strategy, "mode": mode, "k": K},
                corpus={"questions": len(cases)},
                notes="retrieval mode comparison",
            )
        print(f"\n{len(results)} run(s) appended to {history.HISTORY.name}")
    print(f"Per-mode detail written to {RESULTS.name}")


if __name__ == "__main__":
    main()
