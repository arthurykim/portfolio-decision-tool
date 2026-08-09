"""Vector store result parsing, against pymilvus-shaped hits.

test_retrieval_modes.py stubs `vectorstore.search` wholesale, so it can prove
the fusion and fallback logic but never sees how a real hit is unpacked. That
gap let a KeyError ship: pymilvus resolves `hit[key]` against the returned
entity, so `hit["id"]` fails on a collection whose primary field is named
"uid". These tests stub one layer lower — at the client — to cover it without
needing Milvus or a model download.
"""
import pytest

import vectorstore


class FakeHit(dict):
    """Mimics pymilvus' Hit: subscripting resolves against `entity`."""

    def __getitem__(self, key):
        if key == "distance":
            return super().__getitem__("distance")
        return super().__getitem__("entity")[key]


class FakeClient:
    def __init__(self, hits):
        self._hits = hits
        self.search_kwargs = None

    def search(self, **kwargs):
        self.search_kwargs = kwargs
        return [self._hits]

    def list_collections(self):
        return []


@pytest.fixture
def fake_client(monkeypatch):
    hits = [
        FakeHit(entity={"uid": "aaa"}, distance=0.91),
        FakeHit(entity={"uid": "bbb"}, distance=0.42),
    ]
    client = FakeClient(hits)
    monkeypatch.setattr(vectorstore, "_client", lambda: client)
    monkeypatch.setattr(vectorstore.embeddings, "encode_one", lambda text: [0.1, 0.2])
    monkeypatch.setattr(vectorstore.embeddings, "model_name", lambda: "fake/test-model")
    return client


def test_search_reads_the_primary_key_by_its_own_name(fake_client):
    """The regression: "uid", not "id". hit["id"] raises KeyError."""
    assert vectorstore.search("anything") == [("aaa", 0.91), ("bbb", 0.42)]


def test_search_requests_the_uid_output_field(fake_client):
    """uid must be in output_fields or it is absent from the entity."""
    vectorstore.search("anything", k=7)
    assert "uid" in fake_client.search_kwargs["output_fields"]
    assert fake_client.search_kwargs["limit"] == 7


def test_search_returns_empty_when_client_is_unavailable(monkeypatch):
    monkeypatch.setattr(vectorstore, "_client", lambda: None)
    assert vectorstore.search("anything") == []


def test_search_swallows_client_errors(monkeypatch):
    class Boom(FakeClient):
        def search(self, **kwargs):
            raise RuntimeError("milvus went away mid-query")

    monkeypatch.setattr(vectorstore, "_client", lambda: Boom([]))
    monkeypatch.setattr(vectorstore.embeddings, "encode_one", lambda text: [0.1])
    assert vectorstore.search("anything") == []


def test_collection_name_is_namespaced_by_model(monkeypatch):
    monkeypatch.setenv("MILVUS_COLLECTION", "kb")
    monkeypatch.setattr(
        vectorstore.embeddings, "model_name", lambda: "sentence-transformers/all-MiniLM-L6-v2"
    )
    assert vectorstore.collection_name() == "kb_all_MiniLM_L6_v2"


def test_chunk_uid_is_stable_and_content_derived():
    a = vectorstore.chunk_uid("doc.md", "some text")
    assert a == vectorstore.chunk_uid("doc.md", "some text")
    assert a != vectorstore.chunk_uid("doc.md", "some other text")
    assert a != vectorstore.chunk_uid("other.md", "some text")
    assert len(a) == 32
