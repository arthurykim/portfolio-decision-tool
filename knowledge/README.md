# `knowledge/` — the RAG corpus

These markdown files are the *only* thing the chat assistant is allowed to
answer from. There is no other source: retrieval selects passages from here, and
the model is prompted to ground its answer in them. Editing a file here changes
what the assistant knows.

Educational content only — explaining how instruments and mechanics work. No
personalised financial advice, no recommendations to buy or sell.

## Contents

| File | Covers |
|---|---|
| `money-basics.md` | Saving before investing — emergency fund, debt, budgeting |
| `hysa-vs-checking.md` | High-yield savings vs. a traditional bank account |
| `what-are-index-funds.md` | What an index fund is and why it tracks a benchmark |
| `what-are-etfs.md` | ETFs, and how they differ from mutual funds |
| `asset-classes.md` | The asset classes behind the 13 supported tickers |
| `strategies.md` | Classic allocations — 60/40, three-fund, all-weather |
| `metrics.md` | CAGR, volatility, Sharpe, max drawdown |
| `market-history.md` | Notable market episodes present in the price data |
| `what-is-trading.md` | What active trading actually involves, and its trade-offs |
| `how-leverage-works.md` | Leverage, exposure, and why losses amplify too |
| `odds-and-expected-value.md` | Odds, moneyline, and expected value |
| `capital-gains-and-taxes.md` | Gains tax, and why holding longer is treated better |
| `taxable-vs-tax-advantaged.md` | Which account type to hold what in |
| `retirement-accounts.md` | 401(k), Traditional IRA, Roth IRA |
| `using-the-tool.md` | How the Portfolio Decision Tool itself works |

## How these files get chunked

Retrieval does not see whole files — it sees **chunks**, and the default
strategy (`heading` in `rag.CHUNKERS`) splits on markdown headings. Practical
consequences when writing:

- **Every `##` section becomes a retrievable unit.** It should make sense read
  on its own, without the surrounding document.
- **Put the answer near its heading.** A heading that names the concept gives
  both BM25 and the embedding model a strong signal.
- **Keep sections focused.** One idea per section retrieves far better than a
  long section covering several.
- **Spell out synonyms.** BM25 matches on literal words. If people would ask
  about "taxman" or "take-home", having those words present helps — dense
  retrieval covers some of this gap, but only when Milvus is running.

The first `# ` line is the document title and is used to label citations.

## After editing

```bash
task eval:retrieval      # did retrieval quality move?
task vectors:build       # only if Milvus is running — vectors are content-keyed,
                         # so stale ones keep answering until rebuilt
```

Chunks are identified by a hash of their content, so a rebuild replaces cleanly
rather than duplicating. Skipping `vectors:build` after an edit leaves the dense
index answering from the old text.

## Adding a topic

1. Write the file, following the heading conventions above.
2. Add golden questions for it to `eval/golden_qa.jsonl` — untested coverage
   tends to silently regress.
3. Run `task eval:retrieval` to confirm the new file is actually retrievable.
