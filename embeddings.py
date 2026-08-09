"""Local sentence-transformer embeddings.

Runs entirely on-device, so embedding a corpus or a query costs nothing and needs
no API key — the same property that lets the retrieval benchmark run offline.
The model (~90 MB) is downloaded once by HuggingFace on first use and cached
under ~/.cache/huggingface.

The import of `sentence_transformers` is deliberately deferred to first use: it
pulls in torch, which is slow to import and is not needed by the BM25 path that
the app defaults to.
"""
import logging
import os
from functools import lru_cache

logger = logging.getLogger("uvicorn.error")

# all-MiniLM-L6-v2 is the standard small English model: 384 dimensions, ~90 MB,
# fast enough on CPU that batching the whole knowledge base takes ~1 second.
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DIMENSIONS = {
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "sentence-transformers/all-mpnet-base-v2": 768,
    "BAAI/bge-small-en-v1.5": 384,
}


def model_name() -> str:
    return os.environ.get("EMBED_MODEL") or DEFAULT_MODEL


def dimension() -> int:
    """Vector width for the configured model.

    Known models are looked up from the table so the Milvus collection can be
    created without paying to load torch; anything else falls back to asking the
    loaded model itself.
    """
    name = model_name()
    if name in DIMENSIONS:
        return DIMENSIONS[name]
    return _model().get_sentence_embedding_dimension()


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    name = model_name()
    logger.info("loading embedding model %s", name)
    return SentenceTransformer(name)


def available() -> bool:
    """Whether embeddings can be produced at all (is the library installed?).

    Does not load the model — callers use this to decide whether to offer dense
    retrieval before paying the import cost.
    """
    try:
        import sentence_transformers  # noqa: F401
    except Exception:
        return False
    return True


def encode(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Embed a batch of documents. Vectors are L2-normalised, so Milvus inner
    product is exactly cosine similarity."""
    if not texts:
        return []
    vectors = _model().encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [v.tolist() for v in vectors]


def encode_one(text: str) -> list[float]:
    return encode([text])[0]
