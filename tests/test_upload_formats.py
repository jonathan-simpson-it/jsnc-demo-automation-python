"""Tests for the document upload endpoint's accepted file formats."""

import sqlite3
from pathlib import Path

import pytest

from src.core import database as db

# NOTE: this suite requires the project venv / CI (pytest, fastapi TestClient,
# chromadb import chain via src.api.main). The local sandbox lacks those deps.


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point every DB call at a throwaway SQLite file."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield tmp_path / "test.db"


def test_upload_rejects_unsupported_suffix(isolated_db):
    from fastapi.testclient import TestClient
    from src.api.main import app

    client = TestClient(app)
    res = client.post(
        "/api/documents/upload",
        files={"file": ("tool.exe", b"MZ...", "application/octet-stream")},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == (
        "Unsupported file type. Supported: PDF, TXT, MD, DOCX, XLSX"
    )


def test_upload_accepts_docx_and_xlsx_stubs(isolated_db):
    from fastapi.testclient import TestClient
    from src.api.main import app

    client = TestClient(app)
    try:
        for name in ("terms.docx", "ledger.xlsx"):
            res = client.post(
                "/api/documents/upload",
                files={
                    "file": (
                        name,
                        b"not a real docx/xlsx (parse will fail, that's fine)",
                        "application/octet-stream",
                    )
                },
            )
            # The suffix gate now lets .docx/.xlsx through. The stub content is
            # not a real OOXML file, so the route's auto-ingest try/except
            # swallows the failure and reports the upload as 200 / 0 chunks.
            assert res.status_code == 200
            body = res.json()
            assert body["filename"] == name
            assert body["status"] == "uploaded"
            assert body["chunks_ingested"] == 0
            assert body["size"] == len(
                b"not a real docx/xlsx (parse will fail, that's fine)"
            )
    finally:
        # Clean up any documents rows the uploads created on the temp DB.
        conn = sqlite3.connect(str(isolated_db))
        try:
            conn.execute("DELETE FROM documents")
            conn.commit()
        finally:
            conn.close()
