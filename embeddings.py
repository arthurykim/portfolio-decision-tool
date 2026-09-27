"""Local sentence-transformer embeddings: on-device, no API key.

`sentence_transformers` (and torch) is imported on first use, since the default
BM25 path never needs it.
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
    # Known models skip loading torch just to size the Milvus collection.
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
    """Whether sentence-transformers is installed. Does not load the model."""
    try:
        import sentence_transformers  # noqa: F401
    except Exception:
        return False
    return True


def encode(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    # L2-normalised, so Milvus inner product is exactly cosine similarity.
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
