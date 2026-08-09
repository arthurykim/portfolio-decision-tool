"""Milvus-backed dense index over the knowledge base.

This is the *optional* half of retrieval. BM25 (`rag.BM25Index`) always works
with no services running; Milvus adds synonym/paraphrase matching on top. Every
entry point here degrades to "unavailable" rather than raising, so the app, the
tests, and the offline benchmark keep working when Docker is not up.

Start the service with:

    docker compose up -d milvus

then build the index with:

    task vectors:build
"""
import hashlib
import logging
import os
from functools import lru_cache

import embeddings

logger = logging.getLogger("uvicorn.error")

DEFAULT_URI = "http://localhost:19530"
DEFAULT_COLLECTION = "knowledge"

# Inner product over L2-normalised vectors == cosine similarity, and Milvus
# computes IP faster than COSINE (which normalises again on every query).
METRIC = "IP"


def uri() -> str:
    return os.environ.get("MILVUS_URI") or DEFAULT_URI


def collection_name() -> str:
    """Collection is namespaced by model, because vectors from two different
    models are not comparable and must never share a collection."""
    base = os.environ.get("MILVUS_COLLECTION") or DEFAULT_COLLECTION
    suffix = embeddings.model_name().rsplit("/", 1)[-1].replace("-", "_").replace(".", "_")
    return f"{base}_{suffix}"


def chunk_uid(source: str, text: str) -> str:
    """Stable identity for a chunk, used as the Milvus primary key.

    Derived from content rather than position so that re-running the build
    upserts in place instead of duplicating, and so that a dense hit can be
    matched back to the in-memory chunk it came from during fusion.
    """
    digest = hashlib.sha1(f"{source}\x00{text}".encode()).hexdigest()
    return digest[:32]


@lru_cache(maxsize=1)
def _client():
    """Connected MilvusClient, or None when the server is not reachable.

    Cached so a down server costs one timeout per process rather than one per
    query. Call `reset()` after starting Milvus in a long-lived process.
    """
    if not embeddings.available():
        logger.info("dense retrieval off: sentence-transformers is not installed")
        return None
    try:
        from pymilvus import MilvusClient

        client = MilvusClient(uri=uri(), timeout=5)
        client.list_collections()  # forces a real round trip; constructing is lazy
        return client
    except Exception as exc:
        logger.info("dense retrieval off: Milvus unreachable at %s (%s)", uri(), exc)
        return None


def reset() -> None:
    """Drop the cached client so the next call re-probes the server."""
    _client.cache_clear()


def available() -> bool:
    """True when Milvus is reachable AND the collection has been built."""
    client = _client()
    if client is None:
        return False
    try:
        return client.has_collection(collection_name())
    except Exception:
        return False


def build(chunks, batch_size: int = 64) -> int:
    """(Re)build the collection from `chunks`. Returns the number of vectors.

    The collection is dropped first: chunk identities are content-derived, so a
    changed chunking strategy would otherwise leave the old chunks behind as
    orphans that still answer queries.
    """
    client = _client()
    if client is None:
        raise RuntimeError(
            f"Milvus is not reachable at {uri()}. Start it with: docker compose up -d milvus"
        )

    name = collection_name()
    if client.has_collection(name):
        client.drop_collection(name)
    client.create_collection(
        collection_name=name,
        dimension=embeddings.dimension(),
        metric_type=METRIC,
        id_type="string",
        max_length=64,
        primary_field_name="uid",
        vector_field_name="vector",
        auto_id=False,
    )

    total = 0
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        vectors = embeddings.encode([c.text for c in batch])
        client.insert(collection_name=name, data=[
            {
                "uid": chunk_uid(c.source, c.text),
                "vector": vector,
                "source": c.source,
                "heading": c.heading,
            }
            for c, vector in zip(batch, vectors, strict=True)
        ])
        total += len(batch)

    client.flush(collection_name=name)
    logger.info("built Milvus collection %s with %d vectors", name, total)
    return total


def search(query: str, k: int = 10) -> list[tuple[str, float]]:
    """Dense search. Returns [(chunk_uid, similarity)], best first.

    Returns [] rather than raising when the store is unavailable — the caller
    falls back to BM25 alone.
    """
    client = _client()
    if client is None:
        return []
    try:
        hits = client.search(
            collection_name=collection_name(),
            data=[embeddings.encode_one(query)],
            limit=k,
            output_fields=["uid"],
        )
    except Exception as exc:
        logger.warning("dense search failed (%s): %s", type(exc).__name__, exc)
        return []
    if not hits:
        return []
    # Keyed by the primary field's own name, not "id": pymilvus resolves a hit
    # subscript against the returned entity, and this collection names its
    # primary key "uid" (see build()). Asking for h["id"] raises KeyError.
    return [(h["uid"], float(h["distance"])) for h in hits[0]]


def stats() -> dict:
    """Small summary for the readiness probe and the CLI."""
    client = _client()
    if client is None:
        return {"available": False, "reason": "milvus unreachable", "uri": uri()}
    name = collection_name()
    if not client.has_collection(name):
        return {"available": False, "reason": "collection not built", "collection": name}
    try:
        count = client.query(
            collection_name=name, filter="", output_fields=["count(*)"],
        )[0]["count(*)"]
    except Exception:
        count = None
    return {
        "available": True,
        "collection": name,
        "vectors": count,
        "model": embeddings.model_name(),
        "uri": uri(),
    }
