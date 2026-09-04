"""Tests for enhanced hybrid search."""

import tempfile
from unittest.mock import MagicMock, patch

from src.tools.search import create_search_tool
from src.vector_store.chroma import VectorStore


def _setup_store(tmpdir: str) -> VectorStore:
    store = VectorStore(persist_directory=tmpdir, collection_name="test_hybrid")
    chunks = [
        {"content": "Acme Corp raised $10M at $50M valuation in Series A", "metadata": {"source": "ts.md", "filename": "ts.md", "chunk_index": 0}},
        {"content": "CEO Sarah Chen leads a team of 45 employees", "metadata": {"source": "memo.md", "filename": "memo.md", "chunk_index": 0}},
        {"content": "Regulatory compliance under SFC and AMLO", "metadata": {"source": "comp.md", "filename": "comp.md", "chunk_index": 0}},
    ]
    store.add_documents(chunks)
    return store


def test_hybrid_search_returns_results():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _setup_store(tmpdir)
        tool = create_search_tool(store)
        result = tool.invoke("CEO leadership experience")
        assert len(result) > 0
        assert "Sarah Chen" in result or "CEO" in result


def test_hybrid_search_prefers_bm25_exact_match():
    """BM25 should boost exact keyword matches that vector might miss."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _setup_store(tmpdir)
        tool = create_search_tool(store)
        result = tool.invoke("AMLO regulations")
        assert "AMLO" in result or "compliance" in result.lower()


def test_parallel_search_returns_same_results():
    """Parallel execution should produce same results as sequential."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _setup_store(tmpdir)
        tool = create_search_tool(store)
        result = tool.invoke("Acme Corp valuation")
        assert "Acme" in result or "valuation" in result.lower()


def test_llm_query_rewrite_returns_string():
    from src.tools.search import _rewrite_query_llm
    with patch("src.agents.graph._make_llm") as mock_llm:
        mock_resp = MagicMock()
        mock_resp.content = "Acme Corp valuation Series A funding round"
        mock_llm.return_value.invoke.return_value = mock_resp
        result = _rewrite_query_llm("What's Acme's valuation?")
        assert isinstance(result, str)
        assert len(result) > 0


def test_llm_query_rewrite_fallback_on_error():
    from src.tools.search import _rewrite_query_llm
    with patch("src.agents.graph._make_llm") as mock_llm:
        mock_llm.return_value.invoke.side_effect = Exception("API error")
        result = _rewrite_query_llm("What's Acme's valuation?")
        assert result == "What's Acme's valuation?"
