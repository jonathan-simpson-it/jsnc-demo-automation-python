"""Tests for BM25 keyword scoring."""

from src.tools.bm25 import bm25_search


def test_bm25_returns_results():
    corpus = [
        {"content": "Acme Corp raised $10M in Series A funding", "metadata": {"filename": "memo.md"}},
        {"content": "The CEO Sarah Chen has 15 years of experience", "metadata": {"filename": "memo.md"}},
        {"content": "Regulatory compliance under SFC guidelines", "metadata": {"filename": "compliance.md"}},
    ]
    results = bm25_search("CEO experience", corpus, k=3)
    assert len(results) >= 1
    assert results[0]["bm25_score"] > 0
    # The CEO doc should rank highest
    assert "Sarah Chen" in results[0]["content"]


def test_bm25_empty_corpus():
    results = bm25_search("anything", [], k=5)
    assert results == []


def test_bm25_empty_query():
    corpus = [{"content": "test", "metadata": {}}]
    results = bm25_search("", corpus, k=5)
    assert len(results) == 1


def test_bm25_respects_k():
    corpus = [
        {"content": "word " * 10, "metadata": {"filename": f"doc{i}.md"}}
        for i in range(20)
    ]
    results = bm25_search("word", corpus, k=5)
    assert len(results) == 5
