"""Tests for agent tools."""

import tempfile
from src.tools.search import create_search_tool
from src.vector_store.chroma import VectorStore


def _setup_vector_store(tmpdir: str) -> VectorStore:
    """Set up a test vector store with sample data."""
    store = VectorStore(persist_directory=tmpdir, collection_name="test_tools")
    chunks = [
        {
            "content": "Acme Corp raised $10M in Series A at $50M pre-money valuation.",
            "metadata": {"source": "term_sheet.md", "chunk_index": 0},
            "doc_type": "term_sheet",
        },
        {
            "content": "The company has $4M ARR with 120% YoY growth.",
            "metadata": {"source": "memo.md", "chunk_index": 0},
            "doc_type": "investment_memo",
        },
    ]
    store.add_documents(chunks)
    return store


def test_search_tool_creation():
    """Test that search tool is created successfully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _setup_vector_store(tmpdir)
        tool = create_search_tool(store)
        assert tool.name == "search_pe_documents"
        assert "private equity" in tool.description.lower()


def test_search_tool_execution():
    """Test that search tool returns results."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _setup_vector_store(tmpdir)
        tool = create_search_tool(store)
        result = tool.invoke("What is the valuation?")
        assert len(result) > 0
        assert "Acme" in result or "valuation" in result.lower()
