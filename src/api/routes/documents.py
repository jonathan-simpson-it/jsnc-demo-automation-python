"""Document management endpoints."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.core.database import get_db
from src.ingestion.chunker import chunk_documents
from src.ingestion.loader import load_documents

UPLOAD_DIR = Path("data/uploads")


def _file_sizes() -> dict[str, int]:
    """Best-effort filename -> byte size map for the documents list.

    Uploaded files live in ``data/uploads``; demo/sample files live (possibly
    nested) under ``data/sample``. Missing files simply stay out of the map so
    the UI can render an empty size cell.
    """
    sizes: dict[str, int] = {}

    def scan(root: Path, recursive: bool) -> None:
        if not root.exists() or not root.is_dir():
            return
        it = root.rglob("*") if recursive else root.glob("*")
        for p in it:
            if p.is_file():
                sizes.setdefault(p.name, p.stat().st_size)

    scan(UPLOAD_DIR, recursive=False)
    scan(Path("data/sample"), recursive=True)
    return sizes


def _ingest_file(file_path: Path, filename: str) -> tuple[int, str]:
    """Load, chunk, and index a local file into the vector store.

    Returns (chunk_count, doc_type). Returns (0, "") when the file can't be
    parsed or has no extractable text — the caller records the row anyway so
    the user can see the ingestion failed.
    """
    try:
        from src.ingestion.loader import (
            _infer_doc_type,
            _load_pdf_with_pages,
            _load_text_with_lines,
        )

        if file_path.suffix.lower() == ".pdf":
            locations = _load_pdf_with_pages(file_path)
        else:
            locations = _load_text_with_lines(file_path)

        content_text = "\n\n".join(
            loc["text"] for loc in locations if loc["text"].strip()
        )
        if not content_text.strip():
            return 0, ""

        doc_type = _infer_doc_type(file_path)
        doc = {
            "content": content_text,
            "metadata": {"source": str(file_path), "filename": filename},
            "locations": locations,
            "doc_type": doc_type.value,
        }
        chunks = chunk_documents([doc])
        if not chunks:
            return 0, ""
        from src.api.deps import get_vector_store
        get_vector_store().add_documents(chunks)
        return len(chunks), doc_type.value
    except Exception:
        return 0, ""

router = APIRouter()


class DocumentUpdate(BaseModel):
    client_id: int | None = None
    project_id: int | None = None


class TagCreate(BaseModel):
    name: str
    color: str = "#80988f"


class DocumentTagAdd(BaseModel):
    tag_id: int


# ---- Tags ----


@router.get("/tags")
async def list_tags():
    """List all tags."""
    db = get_db()
    try:
        rows = db.execute("SELECT id, name, color FROM tags ORDER BY name").fetchall()
        return {"tags": [dict(r) for r in rows]}
    finally:
        db.close()


@router.post("/tags")
async def create_tag(body: TagCreate):
    """Create a new tag."""
    db = get_db()
    try:
        db.execute(
            "INSERT INTO tags (name, color) VALUES (?, ?)",
            (body.name, body.color),
        )
        db.commit()
        row = db.execute(
            "SELECT id, name, color FROM tags WHERE name = ?", (body.name,)
        ).fetchone()
        return dict(row)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        db.close()


@router.delete("/tags/{tag_id}")
async def delete_tag(tag_id: int):
    """Delete a tag."""
    db = get_db()
    try:
        db.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        db.commit()
        return {"deleted": True}
    finally:
        db.close()


# ---- Document assignment & tagging ----


@router.put("/{doc_id}/assign")
async def assign_document(doc_id: int, body: DocumentUpdate):
    """Assign a document to a client and/or project."""
    db = get_db()
    try:
        updates = []
        params = []
        if body.client_id is not None:
            updates.append("client_id = ?")
            params.append(body.client_id)
        if body.project_id is not None:
            updates.append("project_id = ?")
            params.append(body.project_id)
        if not updates:
            raise HTTPException(status_code=400, detail="Nothing to update")
        params.append(doc_id)
        db.execute(f"UPDATE documents SET {', '.join(updates)} WHERE id = ?", params)
        db.commit()
        return {"updated": True}
    finally:
        db.close()


@router.post("/{doc_id}/tags")
async def add_tag_to_document(doc_id: int, body: DocumentTagAdd):
    """Add a tag to a document."""
    db = get_db()
    try:
        db.execute(
            "INSERT OR IGNORE INTO document_tags (document_id, tag_id) VALUES (?, ?)",
            (doc_id, body.tag_id),
        )
        db.commit()
        return {"added": True}
    finally:
        db.close()


@router.delete("/{doc_id}/tags/{tag_id}")
async def remove_tag_from_document(doc_id: int, tag_id: int):
    """Remove a tag from a document."""
    db = get_db()
    try:
        db.execute(
            "DELETE FROM document_tags WHERE document_id = ? AND tag_id = ?",
            (doc_id, tag_id),
        )
        db.commit()
        return {"removed": True}
    finally:
        db.close()


# ---- Upload ----


@router.post("/upload")
async def upload_document(
    file: UploadFile,
    client_id: int | None = None,
    project_id: int | None = None,
):
    """Upload a document to the knowledge base."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    safe_name = Path(file.filename).name
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid filename")

    supported = {".pdf", ".txt", ".md", ".docx", ".xlsx"}
    if Path(safe_name).suffix.lower() not in supported:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Supported: PDF, TXT, MD, DOCX, XLSX",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_path = UPLOAD_DIR / safe_name

    content = await file.read()
    file_path.write_bytes(content)

    # Auto-ingest into vector store
    ingested, doc_type = _ingest_file(file_path, safe_name)

    # Save to database
    db = get_db()
    try:
        cursor = db.execute(
            """
            INSERT INTO documents
               (filename, chunks, doc_type, client_id, project_id, source)
               VALUES (?, ?, ?, ?, ?, 'upload')
            """,
            (safe_name, ingested, doc_type, client_id, project_id),
        )
        db.commit()
        doc_id = cursor.lastrowid
        return {
            "id": doc_id,
            "filename": safe_name,
            "size": len(content),
            "status": "uploaded",
            "chunks_ingested": ingested,
        }
    finally:
        db.close()


# ---- List (with filters) ----


@router.get("/list")
async def list_documents(
    client_id: int | None = None,
    project_id: int | None = None,
    tag_id: int | None = None,
):
    """List documents with optional filters."""
    db = get_db()
    try:
        query = """
            SELECT d.id, d.filename, d.collection, d.chunks, d.summary,
                   d.doc_type, d.client_id, d.project_id, d.source,
                   d.onedrive_path, d.created_at,
                   c.name as client_name, p.name as project_name
            FROM documents d
            LEFT JOIN clients c ON c.id = d.client_id
            LEFT JOIN projects p ON p.id = d.project_id
        """
        conditions = []
        params = []

        if client_id is not None:
            conditions.append("d.client_id = ?")
            params.append(client_id)
        if project_id is not None:
            conditions.append("d.project_id = ?")
            params.append(project_id)
        if tag_id is not None:
            conditions.append("d.id IN (SELECT document_id FROM document_tags WHERE tag_id = ?)")
            params.append(tag_id)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY d.created_at DESC"

        rows = db.execute(query, params).fetchall()

        # Fetch tags for each document
        documents = []
        sizes = _file_sizes()
        for r in rows:
            doc = dict(r)
            doc["size"] = sizes.get(doc["filename"])
            tag_rows = db.execute(
                """SELECT t.id, t.name, t.color
                   FROM tags t
                   JOIN document_tags dt ON dt.tag_id = t.id
                   WHERE dt.document_id = ?""",
                (doc["id"],),
            ).fetchall()
            doc["tags"] = [dict(t) for t in tag_rows]
            documents.append(doc)

        return {"documents": documents}
    finally:
        db.close()


# ---- Stats (legacy endpoint) ----


@router.get("/stats")
async def get_document_stats():
    """Get document statistics."""
    try:
        from src.api.deps import get_vector_store
        vector_store = get_vector_store()
        count = vector_store.get_collection_count()
        docs = vector_store.list_documents_with_summaries()
    except RuntimeError:
        count = 0
        docs = []

    # Enrich with database info
    db = get_db()
    try:
        db_docs = db.execute(
            """SELECT d.id, d.filename, d.client_id, d.project_id, d.source,
                      c.name as client_name, p.name as project_name
               FROM documents d
               LEFT JOIN clients c ON c.id = d.client_id
               LEFT JOIN projects p ON p.id = d.project_id"""
        ).fetchall()
        db_map = {r["filename"]: dict(r) for r in db_docs}
    finally:
        db.close()

    enriched = []
    for d in docs:
        info = db_map.get(d.get("filename", ""), {})
        d["id"] = info.get("id")
        d["client_name"] = info.get("client_name")
        d["project_name"] = info.get("project_name")
        d["source"] = info.get("source", "upload")
        enriched.append(d)

    return {
        "total_documents": count,
        "collection_name": "pe_documents",
        "documents": enriched,
    }


# ---- Ingest ----


@router.post("/ingest")
async def ingest_documents(client_id: int | None = None, project_id: int | None = None):
    """Ingest all documents from the data directory."""
    data_dir = Path("data/sample")
    if not data_dir.exists():
        raise HTTPException(status_code=404, detail="Data directory not found")

    documents = load_documents(data_dir)
    chunks = chunk_documents(documents)

    from src.api.deps import get_vector_store
    store = get_vector_store()
    store.add_documents(chunks)

    # Mirror rows into the documents table so the Documents page lists them.
    # client_id/project_id optionally attach the files to an isolated namespace.
    _register_ingested(chunks, client_id=client_id, project_id=project_id)

    return {
        "documents_loaded": len(documents),
        "chunks_created": len(chunks),
        "status": "ingested",
    }


def _register_ingested(
    chunks: list[dict],
    client_id: int | None = None,
    project_id: int | None = None,
) -> None:
    """Insert rows for ingested files that aren't in the documents table yet.

    The UI lists the SQLite ``documents`` table while retrieval hits the vector
    store; ingestion must mirror rows or files stay invisible on the Documents
    page. Skips filenames already present so re-ingests are idempotent.
    """
    by_filename: dict[str, int] = {}
    for chunk in chunks:
        fn = chunk.get("metadata", {}).get("filename", "unknown")
        by_filename[fn] = by_filename.get(fn, 0) + 1

    db = get_db()
    try:
        for fn, n in by_filename.items():
            row = db.execute(
                "SELECT id FROM documents WHERE filename = ?", (fn,)
            ).fetchone()
            if row:
                continue
            db.execute(
                """INSERT INTO documents
                      (filename, collection, chunks, doc_type, client_id,
                       project_id, source)
                   VALUES (?, 'pe_documents', ?, '', ?, ?, 'ingest')""",
                (fn, n, client_id, project_id),
            )
        db.commit()
    finally:
        db.close()


# ---- Per-document management: download, re-index, delete ----


def _document_row(doc_id: int):
    """Fetch a document row by id, raising 404 when missing."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return dict(row)
    finally:
        db.close()


@router.get("/{doc_id}/download")
async def download_document(doc_id: int):
    """Download the original file for a document."""
    row = _document_row(doc_id)
    file_path = UPLOAD_DIR / row["filename"]
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Source file is not available on this server",
        )
    return FileResponse(
        file_path,
        filename=row["filename"],
        media_type="application/octet-stream",
    )


@router.post("/{doc_id}/reindex")
async def reindex_document(doc_id: int):
    """Re-ingest a document from its stored source file.

    Drops the document's existing vector chunks first, then reloads and
    re-chunks the file on disk so indexes can't drift from edits.
    """
    row = _document_row(doc_id)
    file_path = UPLOAD_DIR / row["filename"]
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Source file is not available on this server",
        )

    from src.api.deps import get_vector_store
    store = get_vector_store()
    store.delete_document(row["filename"])
    ingested, doc_type = _ingest_file(file_path, row["filename"])

    db = get_db()
    try:
        db.execute(
            "UPDATE documents SET chunks = ?, doc_type = ? WHERE id = ?",
            (ingested, doc_type, doc_id),
        )
        db.commit()
    finally:
        db.close()
    return {
        "id": doc_id,
        "filename": row["filename"],
        "chunks_ingested": ingested,
        "status": "reindexed",
    }


@router.delete("/{doc_id}")
async def delete_document(doc_id: int):
    """Delete a document from the knowledge base.

    Removes the database row (and its tag links) and, when no other document
    shares the same filename, its vector chunks. Vector cleanup is best-effort
    so the endpoint stays reliable even when Chroma is unavailable.
    """
    row = _document_row(doc_id)
    db = get_db()
    try:
        shares = db.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE filename = ? AND id != ?",
            (row["filename"], doc_id),
        ).fetchone()
        db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        db.commit()
    finally:
        db.close()

    if shares["n"] == 0:
        try:
            from src.api.deps import get_vector_store
            get_vector_store().delete_document(row["filename"])
        except Exception:
            pass
    return {"deleted": True}
