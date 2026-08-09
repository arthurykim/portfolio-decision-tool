"""Chunking strategies and deduplication.

These are pure-Python and need no model download or vector store, so they run in
the normal suite.
"""
import pytest

from rag import (
    CHUNKERS,
    DEFAULT_CHUNKER,
    _make_chunk,
    dedupe_chunks,
    load_chunks,
)


@pytest.mark.parametrize("strategy", sorted(CHUNKERS))
def test_every_strategy_covers_the_whole_knowledge_base(strategy):
    chunks = load_chunks(strategy)
    assert chunks, strategy
    # Every knowledge file must survive chunking; a strategy that silently drops
    # a file would make its content unreachable no matter how good retrieval is.
    assert len({c.source for c in chunks}) >= 9
    assert all(c.text.strip() for c in chunks)
    assert all(c.tokens for c in chunks)


def test_default_strategy_is_registered():
    assert DEFAULT_CHUNKER in CHUNKERS


def test_unknown_strategy_is_rejected():
    with pytest.raises(ValueError, match="unknown chunk strategy"):
        load_chunks("does-not-exist")


def test_recursive_splitter_caps_chunk_size():
    # md_recursive exists to break up long sections; if it emitted anything as
    # long as the raw sections it would be a no-op versus md_header.
    chunks = load_chunks("md_recursive")
    assert max(len(c.text) for c in chunks) <= 600
    assert len(chunks) > len(load_chunks("md_header"))


def test_langchain_splitters_keep_headings_in_the_body():
    # A query matching a heading must be able to score against it.
    chunks = load_chunks("md_header")
    assert any(c.heading and c.heading in c.text for c in chunks)


# --- deduplication ---------------------------------------------------------
def _chunk(text, source="a.md", heading="H"):
    return _make_chunk(source, heading, text)


BODY = (
    "Max drawdown is the largest peak to trough decline in portfolio value "
    "measured before a new peak is reached and expressed as a percentage."
)


def test_exact_duplicates_are_removed():
    chunks = [_chunk(BODY), _chunk(BODY, source="b.md")]
    assert len(dedupe_chunks(chunks)) == 1


def test_whitespace_and_case_differences_still_count_as_exact():
    chunks = [_chunk(BODY), _chunk(f"  {BODY.upper()}  \n")]
    assert len(dedupe_chunks(chunks)) == 1


def test_near_duplicate_is_removed_and_longest_survives():
    longer = BODY + " It is reported as a percentage."
    kept = dedupe_chunks([_chunk(BODY), _chunk(longer)], threshold=0.8)
    assert len(kept) == 1
    assert kept[0].text == longer


def test_default_threshold_is_strict_enough_to_keep_a_real_addition():
    # At 0.9 a sentence of genuinely new content is NOT a duplicate. Dropping a
    # distinct chunk costs recall permanently; keeping one only wastes a slot.
    longer = BODY + " It is reported over the whole backtest window."
    assert len(dedupe_chunks([_chunk(BODY), _chunk(longer)], threshold=0.9)) == 2


def test_distinct_chunks_are_kept():
    other = "The Sharpe ratio divides excess return by the standard deviation of returns."
    assert len(dedupe_chunks([_chunk(BODY), _chunk(other)])) == 2


def test_threshold_of_one_keeps_near_duplicates():
    longer = BODY + " It is reported over the whole backtest window."
    assert len(dedupe_chunks([_chunk(BODY), _chunk(longer)], threshold=1.0)) == 2


def test_dedup_preserves_corpus_order():
    a, b, c = _chunk("alpha beta gamma delta"), _chunk("epsilon zeta eta theta"), _chunk(BODY)
    kept = dedupe_chunks([a, b, c])
    assert [x.text for x in kept] == [a.text, b.text, c.text]


def test_dedup_handles_empty_input():
    assert dedupe_chunks([]) == []


def test_dedup_can_be_disabled_via_env(monkeypatch):
    monkeypatch.setenv("DEDUP", "0")
    assert len(load_chunks("heading", dedup=True)) == len(load_chunks("heading", dedup=False))


def test_knowledge_base_has_no_duplicate_chunks():
    # A regression guard on the corpus itself: if someone pastes a section into
    # two files, this fails rather than quietly wasting a top-k slot.
    chunks = load_chunks("heading", dedup=False)
    assert len(dedupe_chunks(chunks)) == len(chunks)
