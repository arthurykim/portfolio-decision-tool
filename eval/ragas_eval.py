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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env import load_env  # noqa: E402

load_env()

from langchain_google_genai import ChatGoogleGenerativeAI  # noqa: E402
from ragas import EvaluationDataset, evaluate  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.metrics import context_precision, context_recall, faithfulness  # noqa: E402

from rag import MODEL, answer, retrieve  # noqa: E402

GOLDEN = Path(__file__).parent / "golden_qa.jsonl"
RESULTS = Path(__file__).parent / "results.json"


def build_dataset() -> EvaluationDataset:
    rows = []
    for line in GOLDEN.read_text().splitlines():
        case = json.loads(line)
        result = answer(case["question"])
        if result["mode"] != "gemini":
            sys.exit("GOOGLE_API_KEY required: assistant is in extractive mode")
        contexts = [p["text"] for p in retrieve(case["question"], k=4)]
        rows.append({
            "user_input": case["question"],
            "retrieved_contexts": contexts,
            "response": result["answer"],
            "reference": case["ground_truth"],
        })
        print(f"  answered: {case['question'][:60]}")
    return EvaluationDataset.from_list(rows)


def main() -> None:
    print(f"Building dataset from {GOLDEN.name} ...")
    dataset = build_dataset()

    judge = LangchainLLMWrapper(ChatGoogleGenerativeAI(model=MODEL, max_output_tokens=2048))
    print("Scoring with RAGAS ...")
    scores = evaluate(
        dataset=dataset,
        metrics=[faithfulness, context_precision, context_recall],
        llm=judge,
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
