"""Hybrid retrieval plumbing: mode selection, RRF fusion, and the guarantee
that a missing/stopped Milvus degrades to BM25 instead of breaking the app.

No Milvus and no model download: the vector store is stubbed, because what needs
testing here is the fallback and fusion logic, not Milvus itself.
"""
import pytest

import rag
import vectorstore
from rag import RRF_K, _make_chunk, _mode, _rrf, retrieve, search


@pytest.fixture(autouse=True)
def _clear_caches():
    rag._uid_index.cache_clear()
    yield
    rag._uid_index.cache_clear()


# --- mode selection --------------------------------------------------------
def test_default_mode_is_bm25(monkeypatch):
    monkeypatch.delenv("RETRIEVAL_MODE", raising=False)
    assert _mode() == "bm25"


def test_mode_comes_from_env(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    assert _mode() == "hybrid"


def test_explicit_mode_beats_env(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    assert _mode("bm25") == "bm25"


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="unknown retrieval mode"):
        _mode("magic")


# --- RRF -------------------------------------------------------------------
def test_rrf_ranks_a_chunk_found_by_both_retrievers_first():
    a, b, c = (_make_chunk("f.md", "H", t) for t in ("alpha", "beta", "gamma"))
    # `b` is retrieved by both; `a` and `c` by only one each. That agreement is
    # the whole point of fusing, so `b` must come out on top.
    fused = _rrf([[a, b], [c, b]])
    assert fused[0][0].text == "beta"


def test_rrf_fuses_equal_chunks_from_different_index_instances():
    # The lexical and dense halves can hand back distinct objects for the same
    # passage; fusion must still combine them rather than emit two singletons.
    lexical = _make_chunk("f.md", "H", "alpha")
    dense = _make_chunk("f.md", "H", "alpha")
    assert lexical is not dense
    fused = _rrf([[lexical], [dense]])
    assert len(fused) == 1
    assert fused[0][1] == pytest.approx(2 / (RRF_K + 1))


def test_rrf_score_matches_the_formula():
    a = _make_chunk("f.md", "H", "alpha")
    [(chunk, score)] = _rrf([[a], [a]])
    assert chunk is a
    assert score == pytest.approx(2 / (RRF_K + 1))


def test_rrf_of_nothing_is_empty():
    assert _rrf([[], []]) == []


# --- graceful degradation --------------------------------------------------
def test_hybrid_falls_back_to_bm25_when_milvus_is_down(monkeypatch):
    monkeypatch.setattr(vectorstore, "search", lambda query, k=10: [])
    hybrid = [c.heading for c, _ in search("what is max drawdown", k=3, mode="hybrid")]
    bm25 = [c.heading for c, _ in search("what is max drawdown", k=3, mode="bm25")]
    assert hybrid == bm25


def test_dense_falls_back_to_bm25_when_milvus_is_down(monkeypatch):
    monkeypatch.setattr(vectorstore, "search", lambda query, k=10: [])
    assert retrieve("what is max drawdown", k=2, mode="dense")


def test_vectorstore_search_returns_empty_when_client_is_unavailable(monkeypatch):
    monkeypatch.setattr(vectorstore, "_client", lambda: None)
    assert vectorstore.search("anything") == []


def test_vectorstore_reports_unavailable_rather_than_raising(monkeypatch):
    monkeypatch.setattr(vectorstore, "_client", lambda: None)
    assert vectorstore.available() is False
    assert vectorstore.stats()["available"] is False


def test_build_refuses_clearly_when_milvus_is_down(monkeypatch):
    monkeypatch.setattr(vectorstore, "_client", lambda: None)
    with pytest.raises(RuntimeError, match="docker compose"):
        vectorstore.build([])


# --- fusion against a stubbed dense index ----------------------------------
def test_dense_hits_are_mapped_back_to_local_chunks(monkeypatch):
    chunks = rag.get_index().chunks
    target = chunks[5]
    uid = vectorstore.chunk_uid(target.source, target.text)
    monkeypatch.setattr(vectorstore, "search", lambda query, k=10: [(uid, 0.9)])

    [(chunk, score)] = search("anything at all", k=1, mode="dense")
    assert (chunk.source, chunk.text) == (target.source, target.text)
    assert score == pytest.approx(0.9)


def test_unknown_uids_from_a_stale_collection_are_ignored(monkeypatch):
    # A collection built from a different chunking strategy returns uids that no
    # longer exist locally; those must not crash or leak into results.
    monkeypatch.setattr(vectorstore, "search", lambda query, k=10: [("deadbeef" * 4, 0.9)])
    results = search("what is max drawdown", k=3, mode="hybrid")
    assert results == search("what is max drawdown", k=3, mode="bm25")


def test_hybrid_promotes_a_chunk_bm25_ranked_low(monkeypatch):
    query = "what is max drawdown"
    lexical = [c for c, _ in rag.get_index().search(query, k=20)]
    # Take something BM25 ranked poorly and let the dense side rank it first.
    underdog = lexical[-1]
    uid = vectorstore.chunk_uid(underdog.source, underdog.text)
    monkeypatch.setattr(vectorstore, "search", lambda q, k=10: [(uid, 0.99)])

    fused = [c for c, _ in search(query, k=4, mode="hybrid")]
    assert underdog in fused
    assert fused.index(underdog) < lexical.index(underdog)


# --- collection naming -----------------------------------------------------
def test_collection_name_is_namespaced_by_model(monkeypatch):
    monkeypatch.setenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    small = vectorstore.collection_name()
    monkeypatch.setenv("EMBED_MODEL", "sentence-transformers/all-mpnet-base-v2")
    # Vectors from two models are not comparable and must not share a collection.
    assert vectorstore.collection_name() != small


def test_chunk_uid_is_stable_and_content_derived():
    first = vectorstore.chunk_uid("a.md", "hello")
    assert first == vectorstore.chunk_uid("a.md", "hello")
    assert first != vectorstore.chunk_uid("a.md", "hello!")
    assert first != vectorstore.chunk_uid("b.md", "hello")
    assert len(first) == 32
