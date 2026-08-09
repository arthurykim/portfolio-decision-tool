"""Integration: the dense/hybrid path against a real Milvus server.

Everything in tests/ runs in-process against stubs. This file is the opposite —
it builds the actual knowledge base into a running Milvus, embeds with the real
sentence-transformer model, and queries it. It is the only place the
embeddings -> Milvus -> RRF fusion chain is exercised end to end.

Not part of the default run. Needs a server:

    task vectors:up          # etcd + MinIO + Milvus, ~1-2 min cold start
    task test:integration

Skips (rather than fails) when Milvus or sentence-transformers is absent, so a
developer without Docker up gets a clean run.
"""
import os

import pytest

import embeddings
import rag
import vectorstore

pytestmark = pytest.mark.integration

# A distinct collection so a run never clobbers the developer's built index.
TEST_COLLECTION = "knowledge_itest"


def _milvus_reachable() -> bool:
    vectorstore.reset()
    return vectorstore._client() is not None


@pytest.fixture(scope="module", autouse=True)
def milvus_collection():
    """Build the real knowledge base into a throwaway collection, once."""
    if not embeddings.available():
        pytest.skip("sentence-transformers not installed")

    os.environ["MILVUS_COLLECTION"] = TEST_COLLECTION
    if not _milvus_reachable():
        pytest.skip(f"Milvus not reachable at {vectorstore.uri()}")

    chunks = rag.load_chunks()
    count = vectorstore.build(chunks)
    assert count == len(chunks)

    yield chunks

    client = vectorstore._client()
    if client is not None and client.has_collection(vectorstore.collection_name()):
        client.drop_collection(vectorstore.collection_name())
    os.environ.pop("MILVUS_COLLECTION", None)
    vectorstore.reset()


@pytest.fixture(autouse=True)
def _clear_rag_caches():
    rag._uid_index.cache_clear()
    yield
    rag._uid_index.cache_clear()


# --- the index itself ------------------------------------------------------
def test_collection_is_namespaced_by_model():
    """Vectors from two models must never share a collection."""
    suffix = embeddings.model_name().rsplit("/", 1)[-1].replace("-", "_").replace(".", "_")
    assert vectorstore.collection_name() == f"{TEST_COLLECTION}_{suffix}"


def test_stats_reports_the_built_collection(milvus_collection):
    stats = vectorstore.stats()
    assert stats["available"] is True
    assert stats["vectors"] == len(milvus_collection)
    assert stats["model"] == embeddings.model_name()


def test_rebuild_replaces_rather_than_duplicates(milvus_collection):
    """build() drops first — a second run must not double the vector count."""
    vectorstore.build(milvus_collection)
    assert vectorstore.stats()["vectors"] == len(milvus_collection)


# --- dense search ----------------------------------------------------------
def test_dense_search_returns_known_chunk_uids(milvus_collection):
    hits = vectorstore.search("what is an index fund?", k=5)
    assert hits, "dense search returned nothing against a built collection"

    known = {vectorstore.chunk_uid(c.source, c.text) for c in milvus_collection}
    uids, scores = zip(*hits, strict=True)
    assert set(uids) <= known
    # Normalised vectors + inner product => cosine, so scores are in [-1, 1]
    # and must come back sorted best-first.
    assert all(-1.01 <= s <= 1.01 for s in scores)
    assert list(scores) == sorted(scores, reverse=True)


def test_dense_matches_a_paraphrase_bm25_cannot(milvus_collection):
    """The reason dense retrieval exists: no shared vocabulary with the source.

    "money you keep after the taxman" shares no content word with the
    capital-gains material, so BM25 has nothing to score on.
    """
    query = "money you keep after the taxman takes a cut of investment profit"
    dense = vectorstore.search(query, k=3)
    assert dense

    by_uid = {vectorstore.chunk_uid(c.source, c.text): c for c in milvus_collection}
    sources = {by_uid[uid].source for uid, _ in dense}
    assert any("tax" in s or "capital-gains" in s for s in sources), sources


# --- fusion through rag.search --------------------------------------------
def test_hybrid_returns_results_and_respects_k(milvus_collection):
    results = rag.search("how does leverage amplify losses?", k=3, mode="hybrid")
    assert len(results) == 3
    assert all(isinstance(c, rag.Chunk) for c, _ in results)


def test_hybrid_differs_from_bm25_alone(milvus_collection):
    """If fusion changed nothing, the dense half would be dead weight."""
    query = "borrowing to invest magnifies both directions"
    bm25 = [c.heading for c, _ in rag.search(query, k=5, mode="bm25")]
    hybrid = [c.heading for c, _ in rag.search(query, k=5, mode="hybrid")]
    assert hybrid != bm25


def test_dense_mode_end_to_end(milvus_collection):
    passages = rag.retrieve("what is an ETF?", k=3, mode="dense")
    assert len(passages) == 3
    assert all(p["text"] for p in passages)


# --- degradation -----------------------------------------------------------
def test_unreachable_milvus_falls_back_instead_of_raising(monkeypatch):
    """The guarantee the whole design rests on, verified against a real socket:
    a dead server yields no dense hits and BM25 still answers."""
    monkeypatch.setenv("MILVUS_URI", "http://127.0.0.1:19531")  # nothing listening
    vectorstore.reset()

    assert vectorstore.available() is False
    assert vectorstore.search("what is an index fund?") == []
    assert rag.search("what is an index fund?", k=3, mode="hybrid")

    vectorstore.reset()
