"""Golden-set loading and file-level ranking metrics shared by the eval scripts."""
import json
from collections.abc import Callable
from pathlib import Path

GOLDEN = Path(__file__).parent / "golden_qa.jsonl"
K = 3


def load_cases() -> list[dict]:
    return [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]


def score(cases: list[dict], rank: Callable[[str], list[str]], k: int = K) -> dict:
    """recall@1, recall@k and MRR of each case's `expected_source` in `rank(question)`.

    `rank` returns source filenames, best first. `cases` in the result holds every
    question's outcome, with `rank` 0 for a miss.
    """
    hits_at_1 = hits_at_k = 0
    reciprocal_ranks = 0.0
    rows = []
    for case in cases:
        expected = case["expected_source"]
        ranked = rank(case["question"])[:k]
        pos = ranked.index(expected) + 1 if expected in ranked else 0
        hits_at_1 += pos == 1
        hits_at_k += pos > 0
        reciprocal_ranks += 1 / pos if pos else 0.0
        rows.append({"question": case["question"], "expected": expected,
                     "retrieved": ranked, "rank": pos})
    n = len(cases)
    return {
        "recall_at_1": round(hits_at_1 / n, 3),
        f"recall_at_{k}": round(hits_at_k / n, 3),
        "mrr": round(reciprocal_ranks / n, 3),
        "cases": rows,
    }


def numeric(result: dict, exclude: tuple[str, ...] = ()) -> dict:
    """The numeric entries of `result`, i.e. what gets recorded to history."""
    return {k: v for k, v in result.items()
            if isinstance(v, (int, float)) and k not in exclude}
