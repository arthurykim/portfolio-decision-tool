"""RAG layer: retrieval over the knowledge base + optional Gemini generation.

Environment knobs: CHUNK_STRATEGY (see CHUNKERS), RETRIEVAL_MODE (see MODES),
DEDUP / DEDUP_THRESHOLD (see dedupe_chunks). BM25 needs nothing installed;
dense/hybrid degrade to BM25 when Milvus or sentence-transformers is missing.
Without GOOGLE_API_KEY, answers are extractive.
"""
import logging
import math
import os
import re
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path

logger = logging.getLogger("uvicorn.error")

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

_STOPWORDS = frozenset([
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has", "have",
    "if", "in", "is", "it", "its", "of", "on", "or", "that", "the", "this", "to", "was",
    "were", "what", "when", "which", "who", "will", "with", "your", "you", "how", "why",
    "does", "do",
])


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9/+-]+", text.lower()) if t not in _STOPWORDS]


@dataclass
class Chunk:
    source: str      # knowledge file name
    heading: str     # section heading
    text: str        # section body (includes heading line)
    tokens: list[str]


def _make_chunk(source: str, heading: str, text: str) -> Chunk:
    return Chunk(source=source, heading=heading, text=text, tokens=_tokenize(text))


def _heading_text(line: str) -> str:
    return line.lstrip("# ").strip()


def _document_title(raw: str) -> str:
    for line in raw.splitlines():
        if line.startswith("# "):
            return _heading_text(line)
    return ""


def _sections(raw: str):
    """(heading, text) per `##` section; the intro before the first `##` is its own section."""
    for sec in re.split(r"\n(?=## )", raw):
        sec = sec.strip()
        if sec:
            yield _heading_text(sec.splitlines()[0]), sec


# --------------------------------------------------------------------------
# Chunking strategies: (source_filename, raw_markdown) -> list[Chunk].
# `heading` is the production default; the others exist for comparison via
# `task eval:chunking`.
# --------------------------------------------------------------------------
def _chunk_by_heading(source: str, raw: str) -> list[Chunk]:
    return [_make_chunk(source, heading, sec) for heading, sec in _sections(raw)]


def _chunk_by_heading_with_title(source: str, raw: str) -> list[Chunk]:
    # Prepending the document title puts the file's topic words in every chunk,
    # which helps when a query names the topic but not the section.
    title = _document_title(raw)
    return [
        _make_chunk(source, heading, f"{title}\n\n{sec}" if title and title != heading else sec)
        for heading, sec in _sections(raw)
    ]


def _chunk_by_paragraph(source: str, raw: str, min_chars: int = 350) -> list[Chunk]:
    """Paragraphs merged up to `min_chars`, labelled with the most recent heading."""
    out: list[Chunk] = []
    heading = _document_title(raw)
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf
        text = "\n\n".join(buf).strip()
        if text:
            out.append(_make_chunk(source, heading, text))
        buf = []

    for block in re.split(r"\n{2,}", raw):
        block = block.strip()
        if not block:
            continue
        if block.startswith("#"):
            flush()
            heading = _heading_text(block)
            continue
        buf.append(block)
        if sum(len(b) for b in buf) >= min_chars:
            flush()
    flush()
    return out


def _chunk_fixed(source: str, raw: str, size: int = 120, overlap: int = 30) -> list[Chunk]:
    """Overlapping word windows that ignore structure — the naive baseline."""
    title = _document_title(raw) or source
    words = re.sub(r"^#+\s*", "", raw, flags=re.M).split()
    out = []
    step = max(size - overlap, 1)
    for i in range(0, max(len(words), 1), step):
        window = words[i:i + size]
        if not window:
            break
        out.append(_make_chunk(source, title, " ".join(window)))
        if i + size >= len(words):
            break
    return out


# --- LangChain splitters ---------------------------------------------------
# Imported lazily so the app still starts without langchain-text-splitters.
MD_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3")]


def _lc_markdown_docs(raw: str):
    from langchain_text_splitters import MarkdownHeaderTextSplitter

    # strip_headers=False keeps the heading line inside the chunk body, matching
    # the hand-written strategies — a query matching a heading must score on it.
    splitter = MarkdownHeaderTextSplitter(MD_HEADERS, strip_headers=False)
    return splitter.split_text(raw)


def _lc_heading(doc, fallback: str) -> str:
    meta = doc.metadata
    for key in ("h3", "h2", "h1"):
        if meta.get(key):
            return meta[key]
    return fallback


def _chunk_langchain_markdown(source: str, raw: str) -> list[Chunk]:
    """Like `heading`, but also splits on `###`."""
    title = _document_title(raw) or source
    out = []
    for doc in _lc_markdown_docs(raw):
        text = doc.page_content.strip()
        if text:
            out.append(_make_chunk(source, _lc_heading(doc, title), text))
    return out


def _chunk_langchain_recursive(
    source: str, raw: str, size: int = 400, overlap: int = 80,
) -> list[Chunk]:
    """`md_header`, then long sections split at the most natural boundary.

    `size` is 400 because the longest section is 687 chars: a larger cap would
    make this identical to `md_header` and the sweep would compare nothing.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    title = _document_title(raw) or source
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    out = []
    for doc in _lc_markdown_docs(raw):
        heading = _lc_heading(doc, title)
        for piece in splitter.split_text(doc.page_content):
            piece = piece.strip()
            if piece:
                out.append(_make_chunk(source, heading, piece))
    return out


CHUNKERS = {
    "heading": _chunk_by_heading,
    "heading_title": _chunk_by_heading_with_title,
    "paragraph": _chunk_by_paragraph,
    "fixed": _chunk_fixed,
    "md_header": _chunk_langchain_markdown,
    "md_recursive": _chunk_langchain_recursive,
}
DEFAULT_CHUNKER = "heading"


# --------------------------------------------------------------------------
# Deduplication. Overlapping windows repeat text by construction, and the
# knowledge base restates definitions across files. Duplicates depress IDF for
# the terms that should discriminate and waste top-k slots.
# --------------------------------------------------------------------------
DEFAULT_DEDUP_THRESHOLD = 0.9


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def dedupe_chunks(chunks: list[Chunk], threshold: float = DEFAULT_DEDUP_THRESHOLD) -> list[Chunk]:
    """Drop chunks whose token-set Jaccard overlap is >= `threshold`, keeping the
    longest of each group. 1.0 means exact matches only.

    The 0.9 default is deliberately strict: dropping a distinct chunk costs
    recall permanently, keeping a near-duplicate only wastes a slot.
    """
    if not chunks:
        return []

    # Exact duplicates first — cheap, and it shrinks the O(n^2) pass below.
    by_text: dict[str, Chunk] = {}
    for chunk in chunks:
        key = _normalized(chunk.text)
        if key not in by_text or len(chunk.text) > len(by_text[key].text):
            by_text[key] = chunk
    unique = list(by_text.values())

    if threshold >= 1.0:
        return _in_original_order(chunks, unique)

    # Longest first, so a survivor is always the longest of its group.
    unique.sort(key=lambda c: len(c.tokens), reverse=True)
    kept: list[Chunk] = []
    kept_sets: list[set[str]] = []
    for chunk in unique:
        tokens = set(chunk.tokens)
        if not tokens:
            continue
        duplicate = False
        for other in kept_sets:
            # Jaccard cannot reach `threshold` unless the smaller set is at
            # least `threshold` of the larger, so skip on size alone first.
            smaller, larger = sorted((len(tokens), len(other)))
            if smaller < threshold * larger:
                continue
            overlap = len(tokens & other)
            if overlap / len(tokens | other) >= threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(chunk)
            kept_sets.append(tokens)
    return _in_original_order(chunks, kept)


def _in_original_order(original: list[Chunk], kept: list[Chunk]) -> list[Chunk]:
    survivors = {id(c) for c in kept}
    return [c for c in original if id(c) in survivors]


def _dedup_threshold() -> float | None:
    raw = os.environ.get("DEDUP")
    if raw is not None and raw.strip().lower() in ("0", "false", "off", "no"):
        return None
    return float(os.environ.get("DEDUP_THRESHOLD") or DEFAULT_DEDUP_THRESHOLD)


def chunk_strategy(strategy: str | None = None) -> str:
    return strategy or os.environ.get("CHUNK_STRATEGY") or DEFAULT_CHUNKER


def load_chunks(
    strategy: str | None = None, dedup: float | None | bool = True,
) -> list[Chunk]:
    """`dedup`: a threshold, True to read it from the environment, False/None to keep all."""
    name = chunk_strategy(strategy)
    try:
        chunker = CHUNKERS[name]
    except KeyError as exc:
        raise ValueError(
            f"unknown chunk strategy {name!r}; choose from {sorted(CHUNKERS)}"
        ) from exc
    chunks: list[Chunk] = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        chunks.extend(chunker(path.name, path.read_text()))

    threshold = _dedup_threshold() if dedup is True else (dedup or None)
    if threshold is not None:
        chunks = dedupe_chunks(chunks, threshold)
    return chunks


class BM25Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.avgdl = sum(len(c.tokens) for c in chunks) / max(len(chunks), 1)
        self.df: dict[str, int] = {}
        for c in chunks:
            for term in set(c.tokens):
                self.df[term] = self.df.get(term, 0) + 1
        self.n = len(chunks)

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log((self.n - df + 0.5) / (df + 0.5) + 1)

    def search(self, query: str, k: int = 4) -> list[tuple[Chunk, float]]:
        q_terms = _tokenize(query)
        scored = []
        for chunk in self.chunks:
            dl = len(chunk.tokens)
            score = 0.0
            for term in q_terms:
                tf = chunk.tokens.count(term)
                if tf == 0:
                    continue
                score += self._idf(term) * (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                )
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


@cache
def get_index(strategy: str | None = None) -> BM25Index:
    return BM25Index(load_chunks(strategy))


# --------------------------------------------------------------------------
# Hybrid retrieval. BM25 matches words, embeddings match meaning, and their
# failures are nearly complementary ("drawdown" vs "how much did I lose?";
# "60/40" blurred by embeddings), so fusing the rankings keeps both wins.
# --------------------------------------------------------------------------
MODES = ("bm25", "dense", "hybrid")
DEFAULT_MODE = "bm25"

# Reciprocal-rank-fusion constant. 60 is the value from the original RRF paper;
# it damps the gap between rank 1 and rank 2 so a single confident-but-wrong
# retriever cannot dominate the fused list.
RRF_K = 60


def _mode(mode: str | None = None) -> str:
    name = mode or os.environ.get("RETRIEVAL_MODE") or DEFAULT_MODE
    if name not in MODES:
        raise ValueError(f"unknown retrieval mode {name!r}; choose from {list(MODES)}")
    return name


@cache
def _uid_index() -> dict:
    """chunk_uid -> Chunk, for mapping Milvus hits back to the chunks BM25 returns."""
    import vectorstore

    return {vectorstore.chunk_uid(c.source, c.text): c for c in get_index().chunks}


def _fusion_key(chunk: Chunk) -> tuple[str, str]:
    # Content, not id(): equal chunks from different index instances must still fuse.
    return (chunk.source, chunk.text)


def _rrf(rankings: list[list[Chunk]]) -> list[tuple[Chunk, float]]:
    scores: dict[tuple[str, str], float] = {}
    chunks: dict[tuple[str, str], Chunk] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            key = _fusion_key(chunk)
            chunks.setdefault(key, chunk)
            scores[key] = scores.get(key, 0.0) + 1 / (RRF_K + rank)
    fused = [(chunks[k], s) for k, s in scores.items()]
    fused.sort(key=lambda x: x[1], reverse=True)
    return fused


def _dense_search(query: str, k: int) -> list[tuple[Chunk, float]]:
    # Unknown uids come from a collection built with another chunking strategy.
    import vectorstore

    uids = _uid_index()
    return [
        (uids[uid], score)
        for uid, score in vectorstore.search(query, k=k)
        if uid in uids
    ]


def search(query: str, k: int = 4, mode: str | None = None) -> list[tuple[Chunk, float]]:
    """Top-k chunks; falls back to BM25 whenever the dense half returns nothing."""
    name = _mode(mode)
    bm25 = get_index()
    if name == "bm25":
        return bm25.search(query, k=k)

    # Fuse over a wider candidate pool than we return: a chunk that is rank 8 in
    # one list and rank 2 in the other should still be able to surface.
    pool = max(k * 5, 20) if name == "hybrid" else k
    dense = _dense_search(query, pool)
    if not dense:
        logger.warning("dense retrieval unavailable; falling back to BM25")
        return bm25.search(query, k=k)
    if name == "dense":
        return dense[:k]

    lexical = [c for c, _ in bm25.search(query, k=pool)]
    return _rrf([lexical, [c for c, _ in dense]])[:k]


def retrieve(query: str, k: int = 4, mode: str | None = None) -> list[dict]:
    # `score` is BM25, cosine, or RRF depending on mode: compare within one call only.
    return [
        {"source": c.source, "heading": c.heading, "text": c.text, "score": round(s, 3)}
        for c, s in search(query, k=k, mode=mode)
    ]


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.6-flash"

SYSTEM_PROMPT = """You are the assistant inside the Portfolio Decision Tool, an
educational backtesting app. Answer questions about finance concepts, asset classes,
allocation strategies, market history, and how this tool computes its metrics.

Ground your answers in the reference passages provided. If the passages don't cover
the question, say so and answer briefly from general knowledge, flagging that it's
outside the tool's knowledge base.

Rules:
- You are not a licensed financial advisor. Never give personalized investment
  advice, recommendations to buy or sell, or predictions about future returns. If
  asked, explain the relevant concepts and suggest consulting a licensed advisor.
- Keep answers concise: a few sentences to two short paragraphs.
- Write plainly for someone new to investing; expand jargon the first time.
- Cite which section you drew from when it's load-bearing, e.g. (metrics.md)."""


def _llm_available() -> bool:
    return bool(os.environ.get("GOOGLE_API_KEY"))


@lru_cache(maxsize=1)
def _client():
    # Long-lived on purpose: a per-call client is closed before the request runs.
    from google import genai

    return genai.Client()


def answer(query: str, history: list[dict] | None = None) -> dict:
    """{answer, sources, mode}; mode is "extractive" (top passage verbatim) when
    there is no API key or generation failed."""
    passages = retrieve(query, k=4)
    sources = [{"source": p["source"], "heading": p["heading"]} for p in passages]

    if _llm_available():
        try:
            return {
                "answer": _generate(query, passages, history or []),
                "sources": sources,
                "mode": "gemini",
            }
        except Exception as exc:
            # Rate limit, network, or bad key: degrade to extractive, but say why.
            logger.warning("Gemini generation failed (%s): %s", type(exc).__name__, exc)

    if not passages:
        return {
            "answer": "I couldn't find anything relevant in the knowledge base. "
                      "Try asking about the supported tickers, metrics like Sharpe or "
                      "max drawdown, or strategies like the 60/40 portfolio.",
            "sources": [],
            "mode": "extractive",
        }
    top = passages[0]
    return {
        "answer": f"From the knowledge base ({top['source']} — {top['heading']}):\n\n"
                  f"{_body(top['text'])}",
        "sources": sources,
        "mode": "extractive",
    }


def _body(section: str) -> str:
    lines = section.splitlines()
    return "\n".join(lines[1:]).strip() if len(lines) > 1 else section


def _generate(query: str, passages: list[dict], history: list[dict]) -> str:
    from google.genai import types

    context = "\n\n---\n\n".join(
        f"[{p['source']} — {p['heading']}]\n{p['text']}" for p in passages
    )
    contents = []
    for turn in history[-6:]:  # last 3 exchanges
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            role = "model" if turn["role"] == "assistant" else "user"
            contents.append(types.Content(
                role=role, parts=[types.Part(text=turn["content"])]
            ))
    contents.append(types.Content(role="user", parts=[types.Part(
        text=f"Reference passages:\n\n{context}\n\nQuestion: {query}"
    )]))

    response = _client().models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=1024,
        ),
    )
    text = (response.text or "").strip()
    if not text:  # safety filter or empty candidate
        raise ValueError("empty response from model")
    return text
