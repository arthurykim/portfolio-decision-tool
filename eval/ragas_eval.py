"""RAGAS evaluation of the chat assistant against the golden Q&A set.

Requires a Gemini API key (GOOGLE_API_KEY in .env) and the eval extras:
    pip install -r eval/requirements-eval.txt
    python eval/ragas_eval.py

Metrics (LLM-judged, no embedding model needed):
    faithfulness       — is the answer grounded in the retrieved contexts?
    context_precision  — are the retrieved contexts relevant to the question?
    context_recall     — do the contexts cover the ground truth?
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env import load_env  # noqa: E402

load_env()

from langchain_google_genai import ChatGoogleGenerativeAI  # noqa: E402
from ragas import EvaluationDataset, evaluate  # noqa: E402
from ragas.run_config import RunConfig  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.metrics import context_precision, context_recall, faithfulness  # noqa: E402

from rag import MODEL, answer, retrieve  # noqa: E402

GOLDEN = Path(__file__).parent / "golden_qa.jsonl"
RESULTS = Path(__file__).parent / "results.json"

# Gemini's free tier allows 5 requests/minute per model, so space calls out.
# Override with EVAL_RPM if you are on a paid tier.
RPM = int(os.environ.get("EVAL_RPM") or 5)
SPACING = 60.0 / max(RPM, 1)


def _throttle(last_call: float) -> float:
    """Sleep so consecutive calls stay under the per-minute quota."""
    wait = SPACING - (time.monotonic() - last_call)
    if wait > 0:
        time.sleep(wait)
    return time.monotonic()


def build_dataset() -> EvaluationDataset:
    rows = []
    cases = [json.loads(l) for l in GOLDEN.read_text().splitlines() if l.strip()]
    last = 0.0
    for i, case in enumerate(cases, 1):
        last = _throttle(last)
        result = answer(case["question"])
        if result["mode"] != "gemini":
            sys.exit(
                "Answer came back in extractive mode. Either GOOGLE_API_KEY is unset, "
                "or the quota is exhausted — check the logged reason above, wait a "
                "minute, and rerun."
            )
        rows.append({
            "user_input": case["question"],
            "retrieved_contexts": [p["text"] for p in retrieve(case["question"], k=4)],
            "response": result["answer"],
            "reference": case["ground_truth"],
        })
        print(f"  [{i}/{len(cases)}] {case['question'][:58]}")
    return EvaluationDataset.from_list(rows)


def main() -> None:
    print(f"Building dataset from {GOLDEN.name} ...")
    dataset = build_dataset()

    judge = LangchainLLMWrapper(ChatGoogleGenerativeAI(
        model=MODEL, max_output_tokens=2048, max_retries=6,
    ))
    print(f"Scoring with RAGAS (judge={MODEL}, {RPM} req/min) ...")
    scores = evaluate(
        dataset=dataset,
        metrics=[faithfulness, context_precision, context_recall],
        llm=judge,
        run_config=RunConfig(max_workers=1, timeout=300),
    )

    df = scores.to_pandas()
    summary = {
        m: round(float(df[m].mean()), 3)
        for m in ("faithfulness", "context_precision", "context_recall")
    }
    RESULTS.write_text(json.dumps(
        {"summary": summary, "cases": json.loads(df.to_json(orient="records"))},
        indent=2,
    ))
    print("\n=== RAGAS summary ===")
    for metric, value in summary.items():
        print(f"  {metric:18} {value:.3f}")
    print(f"\nPer-case results written to {RESULTS}")


if __name__ == "__main__":
    main()
