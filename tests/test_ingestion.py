"""Tests for document ingestion pipeline."""

import json
from pathlib import Path

from src.ingestion.chunker import chunk_documents
from src.ingestion.loader import load_documents, load_single_file


def test_load_single_markdown_file():
    """Test loading a single markdown file."""
    content = load_single_file(Path("data/sample/investment_memos/sample_investment_memo.md"))
    assert len(content) > 0
    assert "investment" in content.lower() or "acme" in content.lower()


def test_load_documents_from_directory():
    """Test loading all documents from a directory."""
    documents = load_documents(Path("data/sample"))
    assert len(documents) > 0
    for doc in documents:
        assert "content" in doc
        assert "metadata" in doc
        assert "doc_type" in doc


def test_chunk_documents():
    """Test document chunking produces multiple chunks from long content."""
    long_content = "This is a test paragraph about private equity. " * 200
    documents = [{"content": long_content, "metadata": {"source": "test.md"}, "doc_type": "investment_memo"}]
    chunks = chunk_documents(documents, chunk_size=500, chunk_overlap=100)
    assert len(chunks) > 1
    for chunk in chunks:
        assert "content" in chunk
        assert "metadata" in chunk
        assert len(chunk["content"]) <= 600  # Some tolerance for sentence boundaries


def test_chunk_preserves_metadata():
    """Test that chunking preserves metadata from parent document."""
    documents = [{"content": "Short content " * 100, "metadata": {"source": "test.pdf"}, "doc_type": "term_sheet"}]
    chunks = chunk_documents(documents, chunk_size=200, chunk_overlap=50)
    for chunk in chunks:
        assert chunk["metadata"]["source"] == "test.pdf"
        assert chunk["doc_type"] == "term_sheet"


def test_auto_signals_are_per_document():
    """Regression: TF-IDF signals must be computed per document.

    The previous implementation computed signals over the whole batch and
    attached them only to the first document's chunk — so one document's
    collection carried another (large) document's routing terms, hijacking
    document detection.
    """
    small_doc = {
        "content": (
            "Apples and oranges grown in the orchard of Alpha Farm. Apples are "
            "sweet. Oranges are citrus. Alpha Farm exports apples."
        ),
        "metadata": {"filename": "alpha_farm.md"},
        "doc_type": "investment_memo",
    }
    big_doc = {
        "content": (
            "Quarterly earnings rose. Diluted EPS grew. GAAP net income doubled. "
            "Diluted EPS guidance. GAAP net income. Quarterly earnings rose again. "
            "GAAP net income guidance. Quarterly earnings rose. Diluted EPS grew. "
            "GAAP net income doubled. Diluted EPS guidance. GAAP net income. "
            "Quarterly earnings rose again. GAAP net income guidance. Quarterly "
            "earnings rose. Diluted EPS grew. GAAP net income doubled. Diluted EPS "
            "guidance. GAAP net income. Quarterly earnings rose again. GAAP net "
            "income guidance. Quarterly earnings rose. Diluted EPS grew."
        ),
        "metadata": {"filename": "big_report.md"},
        "doc_type": "annual_report",
    }
    chunks = chunk_documents([small_doc, big_doc], chunk_size=1000, chunk_overlap=100)

    by_file: dict[str, list[dict]] = {}
    for c in chunks:
        by_file.setdefault(c["metadata"]["filename"], []).append(c)

    alpha_signals = json.loads(
        by_file["alpha_farm.md"][0]["metadata"]["auto_positive_signals"]
    )
    report_signals = json.loads(
        by_file["big_report.md"][0]["metadata"]["auto_positive_signals"]
    )

    # Each document's own vocabulary only
    assert "apples" in alpha_signals or "orchard" in alpha_signals
    assert "diluted" in report_signals or "gaap" in report_signals
    assert "diluted" not in alpha_signals and "gaap" not in alpha_signals
    assert "apples" not in report_signals and "orchard" not in report_signals
