"""Tests for ChromaDB vector store."""

import tempfile
from pathlib import Path
from src.vector_store.chroma import VectorStore


def _get_test_chunks() -> list[dict]:
    """Create test chunks for vector store testing."""
    return [
        {
            "content": "Acme Corp raised $10M in Series A at $50M pre-money valuation.",
            "metadata": {"source": "term_sheet.md", "chunk_index": 0},
            "doc_type": "term_sheet",
        },
        {
            "content": "The company has $4M ARR with 120% YoY growth.",
            "metadata": {"source": "investment_memo.md", "chunk_index": 0},
            "doc_type": "investment_memo",
        },
        {
            "content": "Risk factors include customer concentration and regulatory changes.",
            "metadata": {"source": "investment_memo.md", "chunk_index": 1},
            "doc_type": "investment_memo",
        },
        {
            "content": "Board composition: 2 investor directors, 2 founder directors.",
            "metadata": {"source": "term_sheet.md", "chunk_index": 1},
            "doc_type": "term_sheet",
        },
    ]


def test_vector_store_add_documents():
    """Test adding documents to vector store."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = VectorStore(persist_directory=tmpdir, collection_name="test_add")
        chunks = _get_test_chunks()
        store.add_documents(chunks)
        # Verify documents were added by searching
        results = store.search("valuation", k=2)
        assert len(results) > 0


def test_vector_store_search_relevance():
    """Test that search returns relevant results."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = VectorStore(persist_directory=tmpdir, collection_name="test_search")
        store.add_documents(_get_test_chunks())

        results = store.search("Series A funding round", k=2)
        assert len(results) > 0
        # Results should contain relevant content
        combined_content = " ".join([r["content"] for r in results])
        assert "Acme" in combined_content or "10M" in combined_content or "valuation" in combined_content.lower()


def test_vector_store_get_retriever():
    """Test that get_retriever returns a LangChain-compatible retriever."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = VectorStore(persist_directory=tmpdir, collection_name="test_retriever")
        store.add_documents(_get_test_chunks())

        retriever = store.get_retriever(k=2)
        docs = retriever.invoke("What is the valuation?")
        assert len(docs) > 0
        assert hasattr(docs[0], "page_content")
