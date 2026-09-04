"""Tests for conversations (chat history) repository and API."""

import sqlite3
from pathlib import Path

import pytest

from src.core import database as db


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point every repository call at a throwaway SQLite file."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    # Re-run init so the schema (incl. conversations) exists on the temp DB.
    db.init_db()
    yield tmp_path / "test.db"


def _conv_count(conn: sqlite3.Connection, conversation_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM conversation_messages WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()[0]


def test_create_and_list_conversations(isolated_db):
    conv = db.create_conversation(project_id=None)
    assert conv["id"] > 0
    assert conv["title"] == "New chat"

    convs = db.list_conversations()
    ids = [c["id"] for c in convs]
    assert conv["id"] in ids
    found = next(c for c in convs if c["id"] == conv["id"])
    assert found["message_count"] == 0
    assert found["last_message"] is None


def test_auto_title_and_message_order(isolated_db):
    conv = db.create_conversation(project_id=None)
    db.add_message(conv["id"], "user", "What is the liquidation preference?")
    db.add_message(conv["id"], "assistant", "The liquidation preference is 1x.",
                   agent_type="term_sheet", citations=["[Source 1: x.pdf, page 1, line 2]"],
                   trace=[{"node": "answer", "ms": 10}], confidence=0.9)

    convs = db.list_conversations()
    found = next(c for c in convs if c["id"] == conv["id"])
    assert found["title"] == "What is the liquidation preference?"[:60]
    assert found["message_count"] == 2
    assert found["last_message"] == "The liquidation preference is 1x."

    messages = db.list_messages(conv["id"])
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["citations"] == ["[Source 1: x.pdf, page 1, line 2]"]
    assert messages[1]["trace"] == [{"node": "answer", "ms": 10}]
    assert messages[1]["confidence"] == 0.9
    assert messages[1]["is_error"] is False


def test_error_messages_flagged(isolated_db):
    conv = db.create_conversation()
    db.add_message(conv["id"], "user", "hi")
    db.add_message(conv["id"], "assistant", "Error: boom", is_error=True)
    messages = db.list_messages(conv["id"])
    assert messages[1]["is_error"] is True


def test_delete_conversation_cascades_messages(isolated_db):
    conv = db.create_conversation()
    db.add_message(conv["id"], "user", "hello")
    conn = db.get_db()
    assert _conv_count(conn, conv["id"]) == 1
    conn.close()

    assert db.delete_conversation(conv["id"]) is True
    assert db.delete_conversation(conv["id"]) is False

    conn = db.get_db()
    assert _conv_count(conn, conv["id"]) == 0
    conn.close()


def test_documents_for_project_scopes_by_project(isolated_db):
    conn = db.get_db()
    conn.execute("INSERT INTO clients (name) VALUES ('Acme')")
    client_id = conn.execute("SELECT id FROM clients WHERE name='Acme'").fetchone()[0]
    conn.execute(
        "INSERT INTO projects (name, client_id) VALUES ('Series A', ?)", (client_id,)
    )
    conn.execute(
        "INSERT INTO projects (name, client_id) VALUES ('Series B', ?)", (client_id,)
    )
    ids = conn.execute("SELECT id FROM projects ORDER BY id").fetchall()
    proj_a, proj_b = ids[0][0], ids[1][0]
    conn.execute(
        "INSERT INTO documents (filename, project_id) VALUES ('memo_a.pdf', ?)",
        (proj_a,),
    )
    conn.execute(
        "INSERT INTO documents (filename, project_id) VALUES ('memo_b.pdf', ?)",
        (proj_b,),
    )
    conn.execute(
        "INSERT INTO documents (filename, project_id) VALUES (?, NULL)",
        ("loose.pdf",),
    )
    conn.commit()
    conn.close()

    assert db.documents_for_project(proj_a) == ["memo_a.pdf"]
    assert db.documents_for_project(proj_b) == ["memo_b.pdf"]
    assert "loose.pdf" not in db.documents_for_project(proj_a)


def test_conversation_endpoints_smoke(isolated_db):
    from fastapi.testclient import TestClient
    from src.api.main import app

    client = TestClient(app)

    created = client.post(
        "/api/conversations", json={"project_id": None}
    ).json()
    conv_id = created["id"]
    try:
        listing = client.get("/api/conversations")
        assert listing.status_code == 200
        assert any(c["id"] == conv_id for c in listing.json()["conversations"])

        msgs = client.get(f"/api/conversations/{conv_id}/messages")
        assert msgs.status_code == 200
        assert msgs.json()["messages"] == []

        missing = client.get("/api/conversations/999999/messages")
        assert missing.status_code == 404
    finally:
        client.delete(f"/api/conversations/{conv_id}")
