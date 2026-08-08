"""RAG layer: BM25 retrieval over the knowledge base + optional Gemini generation.

Retrieval is pure Python, so the app works with no API key at all (extractive
mode returns the best-matching passage). When GOOGLE_API_KEY is set, Gemini
writes the answer grounded in the retrieved passages.
"""
import logging
import math
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("uvicorn.error")

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have if in is it its of on or that the "
    "this to was were what when which who will with your you how why does do".split()
)


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


def _document_title(raw: str) -> str:
    """The first level-1 (`# `) heading in a file, or '' if there isn't one."""
    for line in raw.splitlines():
        if line.startswith("# "):
            return line.lstrip("# ").strip()
    return ""


# --------------------------------------------------------------------------
# Chunking strategies
#
# Each strategy maps (source_filename, raw_markdown) -> list[Chunk]. This is the
# main knob to experiment with: rerun `task eval:chunking` after editing one of
# these (or adding a new entry to CHUNKERS) to see how retrieval quality moves.
# `heading` is the production default; the others exist for comparison.
# --------------------------------------------------------------------------
def _chunk_by_heading(source: str, raw: str) -> list[Chunk]:
    """One chunk per `##` section (the material before the first `##` — title
    and intro — becomes its own chunk). This is the default."""
    out = []
    for sec in re.split(r"\n(?=## )", raw):
        sec = sec.strip()
        if not sec:
            continue
        heading = sec.splitlines()[0].lstrip("# ").strip()
        out.append(_make_chunk(source, heading, sec))
    return out


def _chunk_by_heading_with_title(source: str, raw: str) -> list[Chunk]:
    """Like `heading`, but prepend the document title to every section so the
    file's topic words are present in each chunk (helps when a query names the
    topic but not the section)."""
    title = _document_title(raw)
    out = []
    for sec in re.split(r"\n(?=## )", raw):
        sec = sec.strip()
        if not sec:
            continue
        heading = sec.splitlines()[0].lstrip("# ").strip()
        text = f"{title}\n\n{sec}" if title and title != heading else sec
        out.append(_make_chunk(source, heading, text))
    return out


def _chunk_by_paragraph(source: str, raw: str, min_chars: int = 350) -> list[Chunk]:
    """Merge paragraphs into chunks of at least `min_chars`, tracking the most
    recent heading. Finer-grained than whole sections."""
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
            heading = block.lstrip("# ").strip()
            continue
        buf.append(block)
        if sum(len(b) for b in buf) >= min_chars:
            flush()
    flush()
    return out


def _chunk_fixed(source: str, raw: str, size: int = 120, overlap: int = 30) -> list[Chunk]:
    """Fixed-size sliding window over the whole document (word count, with
    overlap). Ignores section structure entirely — the classic naive baseline."""
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


CHUNKERS = {
    "heading": _chunk_by_heading,
    "heading_title": _chunk_by_heading_with_title,
    "paragraph": _chunk_by_paragraph,
    "fixed": _chunk_fixed,
}
DEFAULT_CHUNKER = "heading"


def load_chunks(strategy: str | None = None) -> list[Chunk]:
    """Chunk every knowledge file with the given strategy.

    Strategy resolution: explicit argument > CHUNK_STRATEGY env var > default.
    """
    name = strategy or os.environ.get("CHUNK_STRATEGY") or DEFAULT_CHUNKER
    try:
        chunker = CHUNKERS[name]
    except KeyError:
        raise ValueError(
            f"unknown chunk strategy {name!r}; choose from {sorted(CHUNKERS)}"
        )
    chunks: list[Chunk] = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        chunks.extend(chunker(path.name, path.read_text()))
    return chunks


def _load_chunks() -> list[Chunk]:
    """Backwards-compatible alias for the default chunking."""
    return load_chunks()


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


@lru_cache(maxsize=None)
def get_index(strategy: str | None = None) -> BM25Index:
    """The BM25 index the app queries. Cached per strategy so experiments (and
    the live app via CHUNK_STRATEGY) each build their index once."""
    return BM25Index(load_chunks(strategy))


def retrieve(query: str, k: int = 4) -> list[dict]:
    return [
        {"source": c.source, "heading": c.heading, "text": c.text, "score": round(s, 3)}
        for c, s in get_index().search(query, k=k)
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
    """One long-lived client; a per-call client is closed before the request runs."""
    from google import genai

    return genai.Client()


def answer(query: str, history: list[dict] | None = None) -> dict:
    """Answer a question. Returns {answer, sources, mode}.

    mode is "gemini" when the model wrote the answer, "extractive" when there is
    no API key (or the call failed) and the top passage is returned directly.
    """
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
    """Answer with Gemini, grounded in the retrieved passages."""
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
