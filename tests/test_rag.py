from rag import _tokenize, answer, get_index, retrieve


def test_index_covers_all_knowledge_files():
    sources = {c.source for c in get_index().chunks}
    assert sources >= {
        "asset-classes.md", "market-history.md", "metrics.md",
        "strategies.md", "using-the-tool.md",
        "what-are-etfs.md", "what-are-index-funds.md",
        "retirement-accounts.md", "taxable-vs-tax-advantaged.md",
    }


def test_tokenize_strips_stopwords():
    assert "the" not in _tokenize("what is the sharpe ratio")
    assert "sharpe" in _tokenize("what is the sharpe ratio")


def test_retrieve_ranks_relevant_section_first():
    cases = {
        "what is max drawdown": ("metrics.md", "Max drawdown"),
        "tell me about the all weather portfolio": ("strategies.md", "All Weather portfolio"),
        "what happened in the 2008 crisis": ("market-history.md", "Global financial crisis (2007-2009)"),
        "what is TLT": ("asset-classes.md", "TLT — 20+ year Treasuries"),
    }
    for query, (source, heading) in cases.items():
        top = retrieve(query, k=1)[0]
        assert (top["source"], top["heading"]) == (source, heading), query


def test_retrieve_returns_scores_descending():
    results = retrieve("stocks and bonds portfolio", k=4)
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_answer_extractive_mode_without_credentials(monkeypatch):
    monkeypatch.setattr("rag._claude_available", lambda: False)
    a = answer("what is volatility?")
    assert a["mode"] == "extractive"
    assert "volatility" in a["answer"].lower()
    assert a["sources"]


def test_answer_handles_nonsense_query(monkeypatch):
    monkeypatch.setattr("rag._claude_available", lambda: False)
    a = answer("zzzz qqqq xyzzy")
    assert a["mode"] == "extractive"
    assert a["sources"] == []
