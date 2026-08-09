"""Compare chunking strategies on retrieval quality against the golden set.

Runs fully offline — no API key, no cost — because retrieval is local. For each
strategy registered in rag.CHUNKERS it builds a BM25 index, scores the same
golden questions used by retrieval_eval.py (recall@1, recall@3, MRR), and prints
a side-by-side table. This is the fast feedback loop for chunking experiments:
edit a strategy (or add one) in rag.py, then rerun this.

    python eval/chunking_sweep.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env import load_env  # noqa: E402

load_env()

import history  # noqa: E402
from rag import CHUNKERS, BM25Index, load_chunks  # noqa: E402

GOLDEN = Path(__file__).parent / "golden_qa.jsonl"
RESULTS = Path(__file__).parent / "chunking_results.json"
K = 3


def _load_cases() -> list[dict]:
    return [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]


def score(index: BM25Index, cases: list[dict], k: int = K) -> dict:
    """File-level retrieval metrics for one index over the golden set."""
    hits_at_1 = hits_at_k = 0
    reciprocal_ranks = 0.0
    misses = []
    for case in cases:
        expected = case["expected_source"]
        ranked = [c.source for c, _ in index.search(case["question"], k=k)]
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
    avg_len = sum(len(c.tokens) for c in index.chunks) / max(index.n, 1)
    return {
        "chunks": index.n,
        "avg_tokens": round(avg_len, 1),
        "recall_at_1": round(hits_at_1 / n, 3),
        f"recall_at_{K}": round(hits_at_k / n, 3),
        "mrr": round(reciprocal_ranks / n, 3),
        "misses": misses,
    }


def main() -> None:
    cases = _load_cases()
    results = {}
    for name in CHUNKERS:
        index = BM25Index(load_chunks(name))
        results[name] = score(index, cases)

    RESULTS.write_text(json.dumps(
        {"questions": len(cases), "k": K, "strategies": results}, indent=2,
    ) + "\n")

    ranked = sorted(
        results.items(),
        key=lambda kv: (kv[1]["recall_at_1"], kv[1]["mrr"]),
        reverse=True,
    )

    print(f"Chunking sweep over {len(cases)} golden questions (BM25, no API calls)\n")
    header = f"{'strategy':<16}{'chunks':>8}{'avg_tok':>9}{'recall@1':>10}{'recall@'+str(K):>10}{'MRR':>8}"
    print(header)
    print("-" * len(header))
    for name, m in ranked:
        print(
            f"{name:<16}{m['chunks']:>8}{m['avg_tokens']:>9}"
            f"{m['recall_at_1']:>9.1%}{m[f'recall_at_{K}']:>9.1%}{m['mrr']:>8.3f}"
        )

    best = ranked[0][0]
    if history.enabled():
        for name, res in results.items():
            history.record(
                "chunking",
                {k: v for k, v in res.items()
                 if isinstance(v, (int, float)) and k not in ("chunks", "avg_tokens")},
                config={"strategy": name, "k": K},
                corpus={"questions": len(cases), "chunks": res["chunks"],
                        "avg_tokens": res["avg_tokens"]},
                notes="chunking sweep",
            )
        print(f"\n{len(results)} runs appended to {history.HISTORY.name}")
    print(f"\nBest recall@1: {best!r}. Per-strategy detail written to {RESULTS.name}.")
    print("Try a strategy live with: CHUNK_STRATEGY=<name> task dev")


if __name__ == "__main__":
    main()
