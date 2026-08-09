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

The knowledge base is 15 Markdown files (`knowledge/*.md`). Each is split on `##`
headings into one chunk per section, producing **110 chunks averaging 48.5 tokens**.

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

with `k₁ = 1.5`, `b = 0.75` (the standard defaults), `avgdl = 48.5`, `N = 110`.

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

## 4. Why BM25 is still the default

The obvious alternative is dense retrieval — embed every chunk, embed the query,
rank by cosine similarity. That is now implemented and measured (§8); BM25
remains the *default* because it is the only mode that needs no model download
and no running service:

| | BM25 (chosen) | Embeddings |
|---|---|---|
| Dependencies | none (≈40 lines of Python) | model download or an API call |
| Cost per query | zero | API cost, or RAM for a local model |
| Latency | sub-millisecond | network round trip, or model inference |
| Determinism | identical results every run | varies by model version |
| Offline evaluation | yes — the benchmark needs no key | needs the embedding provider |
| Synonym matching | **no** — this is the real weakness | yes |

BM25 remains the default because it is the only mode that works with nothing
installed and nothing running. It is no longer the *best* mode: §8 shows dense
and hybrid retrieval beating it clearly, and the gap widened as the corpus grew
from 76 to 110 chunks — BM25 fell while dense retrieval held steady, which is the
expected direction as more documents compete for the same words.

**The honest limitation:** BM25 cannot match "how much did I lose at the worst
point?" to a chunk that only ever says "drawdown". No shared token, no score.
Dense retrieval would handle that. The mitigation today is that the knowledge
base is written using the vocabulary users actually type, and generation receives
the top 4 chunks rather than only the top 1 — so a near-miss still lands in
context. **§8 takes the next step: a hybrid of BM25 + embeddings, fused by
reciprocal rank, which closes exactly this gap.**

## 5. Measurement

Retrieval is measured against a golden set of 78 questions, each labelled with the
file that *should* rank first (`eval/golden_qa.jsonl`). Run it with:

```bash
task eval:retrieval        # no API key, no cost, deterministic
```

| Metric | Result | Meaning |
|---|---|---|
| recall@1 | **67.9%** | correct file ranked first (53/78) |
| recall@3 | **88.5%** | correct file within the top 3 (69/78) |
| MRR | **0.776** | mean of 1/rank of the correct file |

The golden set was deliberately made harder: it grew from 16 questions written in
the knowledge base's own vocabulary to **78**, many of them natural-language
paraphrases a real user would type — *"How much cash should I keep set aside for
emergencies?"* rather than *"what is an emergency fund?"*. recall@1 fell from
87.5% to the high 60s as a direct result. Every knowledge file has at least three
labelled questions, so no article is unmeasured.

That drop is the honest number, not a regression. The earlier score measured
queries that shared wording with the documents, which is exactly the case lexical
matching handles best. The paraphrase questions expose the synonym limitation in
§4: **9 of 78 questions retrieve nothing relevant in the top 3 at all**, which
means the assistant answers those from general knowledge rather than from the
knowledge base.

### Where the 25 misses fall

| rank of the correct file | count | consequence |
|---|---|---|
| 2 | 13 | still in the top-4 window the model receives |
| 3 | 3 | still in the window |
| not in top 3 | **9** | the model gets no relevant passage |

The rank-2 and rank-3 cases are mostly genuine ambiguity between two pages that
both answer the question. Two examples:

- *"Why did the 60/40 portfolio struggle in 2022?"* → returns `strategies.md`
  (the 60/40 section, which explicitly discusses its 2022 weakness) above
  `market-history.md` (the 2022 section). Both legitimately answer the question.
- *"What does TLT hold and how risky is it?"* → returns `strategies.md` above
  `asset-classes.md`, because the strategies page discusses TLT's role at length.

Because generation receives the **top 4** chunks, a rank-2 or rank-3 hit is still
in context and the answer is largely unaffected. This is why `recall@3` matters
more than `recall@1` here: the operational question is "did the right passage
reach the model?", not "was it literally first?"

The **9 total misses are the actionable failure**, and they share a shape — the
question and the document use different words for the same idea. Fixing them
needs either synonym-aware retrieval (a hybrid with embeddings) or knowledge-base
text that anticipates how people actually phrase things.

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

## 7. Chunking strategies and deduplication

Chunking is a swappable strategy (`CHUNK_STRATEGY`), and every strategy is scored
on the same golden set by `task eval:chunking`:

| strategy | chunks | avg tok | recall@1 | recall@3 | MRR |
|---|---|---|---|---|---|
| `heading_title` | 110 | 52.1 | **70.5%** | 88.5% | **0.788** |
| `heading` *(default)* | 110 | 48.5 | 67.9% | 88.5% | 0.776 |
| `md_header` | 105 | 50.8 | 66.7% | 88.5% | 0.767 |
| `md_recursive` | 163 | 34.3 | 65.4% | 87.2% | 0.752 |
| `fixed` | 86 | 79.5 | 64.1% | 88.5% | 0.748 |
| `paragraph` | 119 | 41.6 | 59.0% | 84.6% | 0.712 |

`md_header` and `md_recursive` come from **LangChain**'s
`MarkdownHeaderTextSplitter` and `RecursiveCharacterTextSplitter`. The recursive
splitter caps sections at 400 characters, backing off through paragraph → line →
sentence → word boundaries.

> **A result worth recording, because it reversed.** On an earlier 62-question
> golden set and a 9-file corpus, `md_recursive` won every metric (69.4% recall@1
> vs 66.1% for `heading`). After six more articles and 16 more labelled
> questions, it is *fourth*, and `heading_title` leads. Nothing about the
> splitters changed — the earlier result was measured on a corpus small enough
> that a handful of questions decided the ranking. At 78 questions one question
> is still worth 1.3 points, so the top three here are not meaningfully apart
> either. The lesson is to distrust chunker rankings from small benchmarks,
> including this one.

> The 400-char cap is deliberate. The longest section in this corpus is 687
> characters, so the more natural-looking 700 would make `md_recursive` byte-identical
> to `md_header` and the comparison would be measuring nothing.

**Deduplication** (`rag.dedupe_chunks`) runs after chunking. Exact duplicates are
matched on case- and whitespace-normalised text; near-duplicates on Jaccard
overlap of token sets, keeping the longest member of each group. Duplicates are
worth removing for two reasons: they inflate `df`, which *depresses IDF for the
very terms that should discriminate*, and they burn slots in the top-4 window so
the model sees the same passage twice.

The threshold is a strict **0.9**, and the asymmetry is the reason: dropping a
distinct chunk costs recall permanently, while keeping a near-duplicate only
wastes one slot. On today's corpus it removes **nothing** — the knowledge base
has no duplicated sections, and a test asserts this stays true. It earns its
place on overlapping strategies (`fixed`, `md_recursive`) and as a regression
guard against someone pasting a section into two files.

## 8. Dense and hybrid retrieval

`RETRIEVAL_MODE` selects how chunks are ranked:

| mode | how |
|---|---|
| `bm25` *(default)* | lexical only, pure Python, no services |
| `dense` | embeddings only, via Milvus |
| `hybrid` | both, fused by reciprocal rank |

Embeddings are **`all-MiniLM-L6-v2` run locally** through `sentence-transformers`
(384-dim, ~90 MB, no API key, no per-query cost) — this keeps the benchmark free
and offline, the property §5 depends on. Vectors are L2-normalised so Milvus's
inner product *is* cosine similarity. They are stored in **Milvus** (`docker
compose --profile vectors up -d`, then `task vectors:build`).

Fusion is standard RRF with `k=60`:

```
score(d) = Σ  1 / (60 + rank_r(d))
          r∈{bm25, dense}
```

RRF fuses *ranks*, not scores, which matters because a BM25 score (unbounded) and
a cosine similarity (0–1) are not on comparable scales. `k=60` damps the gap
between rank 1 and rank 2 so one confident-but-wrong retriever cannot dominate.

### Measured result (`task eval:modes`)

| chunking | mode | recall@1 | recall@3 | MRR | total misses |
|---|---|---|---|---|---|
| `heading` | bm25 | 67.9% | 88.5% | 0.776 | 9 |
| `heading` | dense | **84.6%** | 93.6% | **0.887** | 5 |
| `heading` | hybrid | 80.8% | 94.9% | 0.876 | 4 |
| `heading_title` | bm25 | 70.5% | 88.5% | 0.788 | 9 |
| `heading_title` | dense | **84.6%** | 93.6% | 0.882 | 5 |
| **`heading_title`** | **hybrid** | 79.5% | **96.2%** | 0.870 | **3** |

**The headline: total misses fall from 9 to 3, and recall@3 rises from 88.5% to
96.2%.** The misses BM25 could not fix were all the same shape — the question and
the document used different words for the same idea — which is precisely what
dense retrieval addresses.

Three results are worth not glossing over:

- **Hybrid is *worse* than dense at recall@1** (79.5% vs 84.6%). Fusing pulls in
  a lexical opinion that is sometimes wrong at rank 1. What hybrid buys is the
  *tail*: recall@3 93.6% → 96.2% and misses 5 → 3. Because generation receives
  the top 4 passages, the tail is what governs answer quality — so hybrid is
  still the better choice here, but "hybrid wins everywhere" would be false, and
  if only rank 1 mattered, dense alone would win.
- **Dense alone still misses 5.** Embeddings blur the exact tokens (`60/40`,
  `7-10 year`) that BM25 nails, which is why fusing beats either half on the tail.
- **Chunking matters less than the retriever.** The spread across all six
  chunking strategies is ~11 points of recall@1; switching BM25 → dense is ~17
  points on its own. Effort spent on embeddings bought more than effort spent on
  splitting.

### Failure behaviour

Dense retrieval is optional at runtime. If `sentence-transformers` is missing, or
Milvus is stopped, or the collection was never built, retrieval **logs a warning
and falls back to BM25** rather than erroring — the same design as the Gemini
fallback in the generation half. Milvus hits whose chunk no longer exists locally
(a collection built under a different `CHUNK_STRATEGY`) are discarded rather than
trusted, since the stored text is stale.

## 9. Known limitations

- **Corpus is small** — 110–163 chunks. BM25's IDF term is noisier on a small `N`;
  re-measure if the knowledge base grows. A 78-question golden set means one
  question is worth 1.3 percentage points, so small differences between
  strategies are not significant (see the reversal noted in §7).
- **The golden set is author-written**, so it may under-represent phrasings a real
  user would try. Queries logged from actual usage would be a better test set.
- **The configuration was chosen on the same questions it is scored on.** These
  numbers are therefore optimistic; a held-out set would be a fairer test of
  whether `heading_title` + hybrid genuinely generalises.
- **No re-ranking.** A cross-encoder over the top ~20 fused candidates is the
  natural next step for recall@1, at the cost of another model dependency.
- **The default is still `bm25`**, so these gains are opt-in: they need Milvus
  running and `task vectors:build` to have been run.
