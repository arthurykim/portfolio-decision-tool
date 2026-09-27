"""Chunk, embed, and load the knowledge base into Milvus.

Rerun after editing knowledge/ or changing CHUNK_STRATEGY / EMBED_MODEL.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env import load_env  # noqa: E402

load_env()

import embeddings  # noqa: E402
import vectorstore  # noqa: E402
from rag import chunk_strategy, load_chunks  # noqa: E402


def main() -> None:
    strategy = chunk_strategy()

    raw = load_chunks(strategy, dedup=False)
    chunks = load_chunks(strategy)
    removed = len(raw) - len(chunks)

    print(f"strategy   {strategy}")
    print(f"chunks     {len(chunks)}" + (f"  ({removed} duplicate(s) dropped)" if removed else ""))
    print(f"model      {embeddings.model_name()} ({embeddings.dimension()}d)")
    print(f"milvus     {vectorstore.uri()}")
    print(f"collection {vectorstore.collection_name()}\n")

    started = time.perf_counter()
    count = vectorstore.build(chunks)
    elapsed = time.perf_counter() - started

    print(f"embedded and indexed {count} chunks in {elapsed:.1f}s")
    print("\nTry it with:  RETRIEVAL_MODE=hybrid task eval:retrieval")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:  # Milvus down — actionable, not a crash
        sys.exit(f"error: {exc}")
