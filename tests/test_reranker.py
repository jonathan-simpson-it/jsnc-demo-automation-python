"""Tests for lightweight re-ranking."""

from src.tools.reranker import rerank_results


def test_rerank_returns_top_k():
    results = [
        {"content": "unrelated text about cooking recipes", "score": 1.5, "metadata": {}},
        {"content": "Acme Corp CEO Sarah Chen leads the company", "score": 1.2, "metadata": {}},
        {"content": "Series A valuation funding round investor", "score": 1.8, "metadata": {}},
    ]
    reranked = rerank_results("Who is the CEO of Acme?", results, k=2)
    assert len(reranked) == 2
    # CEO doc should rank higher after reranking
    assert "Sarah Chen" in reranked[0]["content"]


def test_rerank_empty_input():
    assert rerank_results("query", [], k=5) == []


def test_rerank_preserves_metadata():
    results = [
        {"content": "test content", "score": 1.0, "metadata": {"filename": "test.md"}},
    ]
    reranked = rerank_results("test", results, k=5)
    assert reranked[0]["metadata"]["filename"] == "test.md"
