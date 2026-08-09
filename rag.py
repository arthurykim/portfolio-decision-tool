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


def _load_chunks() -> list[Chunk]:
    """Split each knowledge file into one chunk per '##' section.

    Sections with a heading but no body are skipped. A bare '# Title' line above
    the first '##' carries no information, yet BM25's length normalization scores
    very short documents highly — so "performance metrics" used to retrieve the
    two-token title of metrics.md ahead of any section that answers the question.
    Files whose H1 is followed by real prose keep that prose as a chunk.
    """
    chunks = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        for sec in re.split(r"\n(?=## )", path.read_text()):
            sec = sec.strip()
            if not sec:
                continue
            lines = sec.splitlines()
            if not "\n".join(lines[1:]).strip():
                continue
            chunks.append(Chunk(
                source=path.name,
                heading=lines[0].lstrip("# ").strip(),
                text=sec,
                tokens=_tokenize(sec),
            ))
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


@lru_cache(maxsize=1)
def get_index() -> BM25Index:
    return BM25Index(_load_chunks())


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
