# How retrieval works

The chat assistant is a RAG pipeline with two independent halves:

```
question ──▶ [ RETRIEVAL ]  ──▶ top-k passages ──▶ [ GENERATION ] ──▶ answer
              BM25, local                            Gemini, remote
              free, deterministic                    metered, probabilistic
```

They are deliberately decoupled. Retrieval is pure Python with no network call, so
it is **free to run, deterministic, and measurable offline**. Generation is a
thin wrapper over an API. If the API key is missing, rate-limited, or fails, the
pipeline degrades to returning the top passage verbatim rather than erroring —
retrieval alone is still a usable product.

This document explains the retrieval half, because that is the half this project
actually implements.

---

## 1. Chunking

The knowledge base is 9 Markdown files (`knowledge/*.md`). Each is split on `##`
headings into one chunk per section, producing **61 chunks averaging 37.8 tokens**.

```python
sections = re.split(r"\n(?=## )", raw)
```

Section-level chunking was chosen over the two common alternatives:

| Strategy | Why not |
|---|---|
| Whole file | A file like `asset-classes.md` covers 12 unrelated funds. Retrieving it for "what is TLT" drags in 11 irrelevant ones, diluting the context window. |
| Fixed-size windows (e.g. 512 tokens) | Splits mid-sentence and mid-table, and cuts definitions away from their headings. |

Markdown headings are a **human-authored semantic boundary** — the author already
decided where one idea ends and the next begins. Reusing that costs nothing and
beats guessing. The heading text is also kept inside the chunk body, so a query
matching the heading scores against it.

The tradeoff: sections vary in length (some are 20 tokens, some 90). BM25's
length normalization (§2) is what keeps that from biasing results.

## 2. Scoring: BM25

BM25 ranks a chunk *D* against query *Q* as:

```
score(D, Q) = Σ  IDF(qᵢ) ·        f(qᵢ, D) · (k₁ + 1)
             qᵢ∈Q            ─────────────────────────────────
                             f(qᵢ, D) + k₁ · (1 − b + b · |D|/avgdl)
```

with `k₁ = 1.5`, `b = 0.75` (the standard defaults), `avgdl = 37.8`, `N = 61`.

Three ideas do the work:

**Term frequency, with diminishing returns.** A chunk mentioning "drawdown" five
times is more relevant than one mentioning it once — but not five times more.
`k₁` controls how fast the payoff flattens.

**IDF — rare words matter more.** A term appearing in few chunks is more
discriminating:

```
IDF(t) = ln( (N − df + 0.5) / (df + 0.5) + 1 )
```

**Length normalization.** Without it, long chunks win purely by containing more
words. `b = 0.75` divides by length relative to the corpus average, so a 90-token
section doesn't outrank a 25-token section that is actually about the topic.

### Worked example

Query: **"what is max drawdown"**

Tokenization drops stopwords (`what`, `is`) leaving `["max", "drawdown"]`:

| term | df | IDF |
|---|---|---|
| `max` | 3 | 2.874 |
| `drawdown` | 4 | 2.623 |

Scoring every chunk and taking the top 3:

| score | chunk |
|---|---|
| **7.461** | `metrics.md` — Max drawdown |
| 5.620 | `using-the-tool.md` — What the tool does |
| 2.748 | `market-history.md` — COVID crash (Feb–Mar 2020) |

The correct section wins because it contains both rare terms repeatedly. The
runner-up mentions drawdown once in passing. Note the third result is *related*
but not *definitional* — it describes a specific drawdown event. This is the
expected shape: BM25 ranks by lexical overlap, not by intent.

## 3. Tokenization

```python
re.findall(r"[a-z0-9/+-]+", text.lower())
```

Lowercased, with a 39-word stopword list removed. The character class deliberately
keeps `/`, `+`, and `-` so that finance-specific tokens survive intact:
**`60/40`**, **`7-10`** (year Treasury), **`20+`** (year Treasury). A naive
`\w+` split would shred `60/40` into `60` and `40`, and a query for the 60/40
portfolio would then match any chunk containing either number.

## 4. Why BM25 instead of embeddings?

The obvious alternative is dense retrieval — embed every chunk, embed the query,
rank by cosine similarity. BM25 was chosen deliberately:

| | BM25 (chosen) | Embeddings |
|---|---|---|
| Dependencies | none (≈40 lines of Python) | model download or an API call |
| Cost per query | zero | API cost, or RAM for a local model |
| Latency | sub-millisecond | network round trip, or model inference |
| Determinism | identical results every run | varies by model version |
| Offline evaluation | yes — the benchmark needs no key | needs the embedding provider |
| Synonym matching | **no** — this is the real weakness | yes |

At this corpus size the tradeoff strongly favours BM25. With 61 chunks of
domain-specific vocabulary, queries and documents share terminology: someone
asking about "max drawdown" uses those words, because they are the words the
concept has. Lexical matching is sufficient, and the measured recall (§5)
confirms it.

**The honest limitation:** BM25 cannot match "how much did I lose at the worst
point?" to a chunk that only ever says "drawdown". No shared token, no score.
Dense retrieval would handle that. The mitigation today is that the knowledge
base is written using the vocabulary users actually type, and generation receives
the top 4 chunks rather than only the top 1 — so a near-miss still lands in
context. If the corpus grew past a few hundred chunks, or if user phrasing
diverged from the source vocabulary, a hybrid (BM25 + embeddings, fused by
reciprocal rank) would be the next step.

## 5. Measurement

Retrieval is measured against a golden set of 16 questions, each labelled with the
file that *should* rank first (`eval/golden_qa.jsonl`). Run it with:

```bash
task eval:retrieval        # no API key, no cost, deterministic
```

| Metric | Result | Meaning |
|---|---|---|
| recall@1 | **87.5%** | correct file ranked first (14/16) |
| recall@3 | **100%** | correct file within the top 3 (16/16) |
| MRR | **0.938** | mean of 1/rank of the correct file |

### The two misses, and why they aren't failures

Both rank the correct file **second**, and both are genuine ambiguities:

- *"Why did the 60/40 portfolio struggle in 2022?"* → returns `strategies.md`
  (the 60/40 section, which explicitly discusses its 2022 weakness) above
  `market-history.md` (the 2022 section). Both legitimately answer the question.
- *"What does TLT hold and how risky is it?"* → returns `strategies.md` above
  `asset-classes.md`, because the strategies page discusses TLT's role at length.

Because generation receives the **top 4** chunks, a rank-2 hit is still in
context and the answer is unaffected. This is why `recall@3` matters more than
`recall@1` for this pipeline: the operational question is "did the right passage
reach the model?", not "was it literally first?"

### Why a labelled golden set rather than eyeballing

Without labels, "does retrieval work?" can only be answered by spot-checking, which
silently overfits to the queries the author happens to try. Labelling the expected
source makes regressions *visible*: changing the tokenizer, the chunking strategy,
or `k₁`/`b` immediately moves the numbers. The benchmark is fast, free, and
deterministic, so it can run on every change.

## 6. What the generation half adds

The top 4 chunks are formatted with their source and heading, and sent to Gemini
with a system prompt that constrains it to the passages, forbids personalized
financial advice, and asks for citations. Answer quality is measured separately by
RAGAS (`task eval`) on faithfulness, context precision, and context recall.

Retrieval determines the *ceiling* on answer quality — the model cannot cite what
it was never given. That is why this half is measured first and independently.

## 7. Known limitations

- **No synonym or paraphrase matching** (§4). The main structural weakness.
- **Corpus is small** — 61 chunks. BM25's IDF term is noisier on a small `N`;
  these numbers should be re-measured if the knowledge base grows substantially.
- **The golden set is author-written**, so it may under-represent phrasings a real
  user would try. Queries logged from actual usage would be a better test set.
- **No re-ranking.** A cross-encoder over the top ~20 candidates would likely fix
  both current misses, at the cost of a model dependency.
