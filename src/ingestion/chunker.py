"""Text chunking strategies for document processing."""

import json

from langchain_text_splitters import RecursiveCharacterTextSplitter

from config.settings import settings
from src.utils.doc_signals import extract_doc_signals


def chunk_documents(
    documents: list[dict],
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[dict]:
    """Split documents into smaller chunks for embedding.

    Args:
        documents: List of document dictionaries with 'content' and 'metadata'.
        chunk_size: Maximum chunk size in characters. Defaults to settings.
        chunk_overlap: Overlap between chunks. Defaults to settings.

    Returns:
        List of chunk dictionaries with content, metadata, and chunk_index.
    """
    chunk_size = chunk_size or settings.chunk_size
    chunk_overlap = chunk_overlap or settings.chunk_overlap

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks = []
    for doc in documents:
        locations = doc.get("locations", [])
        text_chunks = splitter.split_text(doc["content"])

        doc_chunks = []
        for i, chunk_text in enumerate(text_chunks):
            chunk_metadata = doc["metadata"].copy()
            chunk_metadata["chunk_index"] = i
            chunk_metadata["total_chunks"] = len(text_chunks)

            # Find the best location match for this chunk
            location = _find_chunk_location(chunk_text, doc["content"], locations)
            if location:
                chunk_metadata["page"] = location.get("page", 1)
                chunk_metadata["line"] = location.get("line", 1)
            else:
                chunk_metadata["page"] = 1
                chunk_metadata["line"] = 1

            # Tag chunks that contain tables
            from src.ingestion.tables import extract_tables_from_text
            tables = extract_tables_from_text(chunk_text)
            if tables:
                chunk_metadata["has_table"] = True
                chunk_metadata["table_count"] = len(tables)

            doc_chunks.append({
                "content": chunk_text,
                "metadata": chunk_metadata,
                "doc_type": doc.get("doc_type", "unknown"),
            })

        # Generate TF-IDF auto-signals PER DOCUMENT. Computing them over the
        # whole batch lets large documents (e.g. a 489-chunk annual report)
        # dominate the vocabulary, and the previous code attached that single
        # batch-level signal set to the FIRST document's chunk only — so one
        # document carried another document's routing terms.
        auto_signals = extract_doc_signals(doc_chunks)
        if auto_signals[0]:  # positive signals found
            # Attach to the first chunk's metadata so VectorStore can read it
            doc_chunks[0]["metadata"]["auto_positive_signals"] = json.dumps(auto_signals[0])
            doc_chunks[0]["metadata"]["auto_negative_signals"] = json.dumps(auto_signals[1])

        # Auto-generate a one-paragraph summary for sidebar display.
        # Stored in collection metadata alongside auto-signals.
        filename = doc["metadata"].get("filename", "unknown")
        try:
            from src.ingestion.summarize import summarize_document
            summary = summarize_document(doc["content"], filename)
            if summary:
                doc_chunks[0]["metadata"]["auto_summary"] = summary
        except Exception:
            pass  # non-fatal: summary is a UX aid, not critical

        chunks.extend(doc_chunks)

    return chunks


def _find_chunk_location(chunk_text: str, full_text: str, locations: list[dict]) -> dict | None:
    """Find the page/line location for a chunk based on its position in the document."""
    if not locations:
        return None

    # Find where this chunk appears in the full text
    chunk_start = full_text.find(chunk_text[:100])
    if chunk_start == -1:
        return locations[0] if locations else None

    # Walk through locations to find which page/line contains this offset
    current_offset = 0
    for loc in locations:
        text_len = len(loc["text"]) + 2  # +2 for paragraph break
        if current_offset + text_len > chunk_start:
            return loc
        current_offset += text_len

    return locations[-1] if locations else None
