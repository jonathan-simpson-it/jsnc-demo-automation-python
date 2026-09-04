#!/usr/bin/env python3
"""CLI script for ingesting documents into the vector store."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from src.core.database import get_db
from src.ingestion.chunker import chunk_documents
from src.ingestion.loader import load_documents
from src.vector_store.chroma import VectorStore


def _register_documents(
    chunks: list[dict], client_id: int | None = None, project_id: int | None = None
) -> None:
    """Register ingested files in the documents table so the Documents page shows them.

    The vector store is the source of truth for retrieval, but the UI lists the
    SQLite ``documents`` table. Ingestion must mirror rows there or freshly
    indexed files stay invisible (legacy gap: 15 docs existed in Chroma with no
    rows). Files already registered are skipped, so re-running ingestion is
    idempotent.
    """
    by_filename: dict[str, int] = {}
    for chunk in chunks:
        fn = chunk["metadata"].get("filename", "unknown")
        by_filename[fn] = by_filename.get(fn, 0) + 1
    db = get_db()
    try:
        for fn, n in by_filename.items():
            row = db.execute(
                "SELECT id FROM documents WHERE filename = ?", (fn,)
            ).fetchone()
            if row:
                db.execute(
                    "UPDATE documents SET chunks = ? WHERE id = ?", (n, row["id"])
                )
                continue
            db.execute(
                """INSERT INTO documents (filename, collection, chunks, doc_type,
                                        client_id, project_id, source)
                   VALUES (?, 'pe_documents', ?, '', ?, ?, 'ingest')""",
                (fn, n, client_id, project_id),
            )
        db.commit()
    finally:
        db.close()


def main():
    """Main ingestion workflow."""
    print("PE AI Engineering - Document Ingestion")
    print("=" * 50)

    # Load documents
    data_dir = Path("data/sample")
    print(f"\nLoading documents from {data_dir}...")

    try:
        documents = load_documents(data_dir)
    except FileNotFoundError:
        print(f"Error: Data directory not found at {data_dir}")
        sys.exit(1)

    print(f"Loaded {len(documents)} documents")

    # Chunk documents
    print("\nChunking documents...")
    chunks = chunk_documents(documents)
    print(f"Created {len(chunks)} chunks")

    # Add to vector store
    print(f"\nAdding to vector store at {settings.chroma_persist_directory}...")
    store = VectorStore()
    store.add_documents(chunks)
    print(f"Added {len(chunks)} chunks to vector store")

    # Mirror rows into the documents table (client/project optional: pass
    # --client-id / --project-id to attach ingests to an isolated namespace)
    _register_documents(chunks)

    # Verify
    count = store.get_collection_count()
    print(f"\nVector store now contains {count} documents")

    print("\nIngestion complete!")


if __name__ == "__main__":
    main()
