"""Score every chunking strategy in rag.CHUNKERS on the golden set (BM25, offline).

    python eval/chunking_sweep.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env import load_env  # noqa: E402

load_env()

import history  # noqa: E402
from scoring import K, load_cases, numeric, score  # noqa: E402

from rag import CHUNKERS, BM25Index, load_chunks  # noqa: E402

RESULTS = Path(__file__).parent / "chunking_results.json"


def score_index(index: BM25Index, cases: list[dict]) -> dict:
    result = score(cases, lambda q: [c.source for c, _ in index.search(q, k=K)])
    rows = result.pop("cases")
    return {
        "chunks": index.n,
        "avg_tokens": round(index.avgdl, 1),
        **result,
        "misses": [r for r in rows if r["rank"] != 1],
    }


def main() -> None:
    cases = load_cases()
    results = {name: score_index(BM25Index(load_chunks(name)), cases) for name in CHUNKERS}

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
                numeric(res, exclude=("chunks", "avg_tokens")),
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
