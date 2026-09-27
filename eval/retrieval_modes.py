"""Compare bm25 vs dense vs hybrid on the golden set, same metrics as retrieval_eval.py.

Needs `task vectors:up && task vectors:build`. Modes whose backend is unavailable
are reported as skipped rather than silently scoring as BM25.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env import load_env  # noqa: E402

load_env()

import history  # noqa: E402
from scoring import K, load_cases, numeric, score  # noqa: E402

import vectorstore  # noqa: E402
from rag import MODES, chunk_strategy, retrieve  # noqa: E402

RESULTS = Path(__file__).parent / "mode_results.json"


def score_mode(mode: str, cases: list[dict]) -> dict:
    result = score(cases, lambda q: [p["source"] for p in retrieve(q, k=K, mode=mode)])
    rows = result.pop("cases")
    return {
        **result,
        "total_misses": sum(r["rank"] == 0 for r in rows),
        "misses": [r for r in rows if r["rank"] != 1],
    }


def main() -> None:
    cases = load_cases()
    strategy = chunk_strategy()
    dense_ok = vectorstore.available()

    results, skipped = {}, []
    for mode in MODES:
        if mode != "bm25" and not dense_ok:
            skipped.append(mode)
            continue
        results[mode] = score_mode(mode, cases)

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
                numeric(res),
                config={"strategy": strategy, "mode": mode, "k": K},
                corpus={"questions": len(cases)},
                notes="retrieval mode comparison",
            )
        print(f"\n{len(results)} run(s) appended to {history.HISTORY.name}")
    print(f"Per-mode detail written to {RESULTS.name}")


if __name__ == "__main__":
    main()
