"""SQLite database for clients, projects, documents, tags, and chat history."""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path("data/platform.db")


def get_db() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            client_id INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            collection TEXT DEFAULT 'pe_documents',
            chunks INTEGER DEFAULT 0,
            summary TEXT DEFAULT '',
            doc_type TEXT DEFAULT '',
            client_id INTEGER,
            project_id INTEGER,
            source TEXT DEFAULT 'upload',
            onedrive_id TEXT,
            onedrive_path TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT DEFAULT '#80988f'
        );

        CREATE TABLE IF NOT EXISTS document_tags (
            document_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY (document_id, tag_id),
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS onedrive_tokens (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            access_token TEXT,
            refresh_token TEXT,
            expires_at TEXT,
            user_email TEXT,
            connected_at TEXT DEFAULT (datetime('now'))
        );

        -- Regulatory Radar feed (SFC/HKMA scraped circulars and releases)
        CREATE TABLE IF NOT EXISTS regulatory_feed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key TEXT NOT NULL,
            external_id TEXT NOT NULL,
            regulator TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            issued_at TEXT,
            fetched_at TEXT DEFAULT (datetime('now')),
            summary TEXT DEFAULT '',
            chunks INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending' CHECK (status IN ('pending','ingested','skipped','error')),
            UNIQUE(source_key, external_id)
        );

        -- Chat history, grouped by project. project_id NULL = Global workspace.
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            title TEXT NOT NULL DEFAULT 'New chat',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS conversation_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            agent_type TEXT,
            citations TEXT DEFAULT '[]',
            trace TEXT DEFAULT '[]',
            confidence REAL,
            is_error INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );

        -- Human review queue for agent drafts awaiting approval/edit/rejection.
        CREATE TABLE IF NOT EXISTS review_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER,
            query TEXT NOT NULL,
            draft_answer TEXT NOT NULL,
            agent_type TEXT,
            citations TEXT DEFAULT '[]',
            trace TEXT DEFAULT '[]',
            confidence REAL,
            reason TEXT DEFAULT '',
            status TEXT DEFAULT 'pending' CHECK (status IN ('pending','approved','edited','rejected')),
            edited_answer TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.close()


# ---- Conversations / messages repository ----

def _to_iso(row: dict) -> dict:
    """Mark SQLite UTC timestamps as UTC (trailing Z) for JS Date parsing."""
    for key in ("created_at", "updated_at"):
        value = row.get(key)
        if value and not str(value).endswith("Z"):
            row[key] = f"{value}Z"
    return row


def create_conversation(project_id: int | None = None, title: str = "New chat") -> dict:
    """Create a conversation. project_id=None means the Global workspace."""
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO conversations (project_id, title) VALUES (?, ?)",
        (project_id, title),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM conversations WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    conn.close()
    return _to_iso(dict(row))


def list_conversations() -> list[dict]:
    """List conversations newest first with message count and last message preview."""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT c.id, c.project_id, c.title, c.created_at, c.updated_at,
               (SELECT COUNT(*) FROM conversation_messages m
                 WHERE m.conversation_id = c.id) AS message_count,
               (SELECT m.content FROM conversation_messages m
                 WHERE m.conversation_id = c.id ORDER BY m.id DESC LIMIT 1) AS last_message
        FROM conversations c
        ORDER BY c.updated_at DESC
        """
    ).fetchall()
    conn.close()
    return [_to_iso(dict(r)) for r in rows]


def get_conversation(conversation_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    conn.close()
    return _to_iso(dict(row)) if row else None


def delete_conversation(conversation_id: int) -> bool:
    conn = get_db()
    cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def add_message(
    conversation_id: int,
    role: str,
    content: str,
    agent_type: str | None = None,
    citations: list | None = None,
    trace: list | None = None,
    confidence: float | None = None,
    is_error: bool = False,
) -> dict:
    """Persist a message and touch the conversation (auto-title from first user turn)."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO conversation_messages
           (conversation_id, role, content, agent_type, citations, trace, confidence, is_error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            conversation_id,
            role,
            content,
            agent_type,
            json.dumps(citations or []),
            json.dumps(trace or []),
            confidence,
            1 if is_error else 0,
        ),
    )
    message_id = cur.lastrowid
    if role == "user" and content.strip():
        conn.execute(
            """UPDATE conversations
               SET title = ?, updated_at = datetime('now')
               WHERE id = ? AND title = 'New chat'""",
            (content.strip()[:60], conversation_id),
        )
    else:
        conn.execute(
            "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
            (conversation_id,),
        )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM conversation_messages WHERE id = ?", (message_id,)
    ).fetchone()
    conn.close()
    return _to_iso(dict(row))


def list_messages(conversation_id: int) -> list[dict]:
    """Return all messages for a conversation, oldest first, with parsed JSON fields."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM conversation_messages WHERE conversation_id = ? ORDER BY id ASC",
        (conversation_id,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = _to_iso(dict(r))
        d["citations"] = json.loads(d.get("citations") or "[]")
        d["trace"] = json.loads(d.get("trace") or "[]")
        d["is_error"] = bool(d.get("is_error"))
        out.append(d)
    return out


def documents_for_project(project_id: int) -> list[str]:
    """Filenames of documents assigned to a project (strict retrieval scope)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT filename FROM documents WHERE project_id = ?", (project_id,)
    ).fetchall()
    conn.close()
    return [r["filename"] for r in rows]


# ---- Review queue repository ----

def _review_row(row) -> dict:
    """dict(row) with UTC timestamps and JSON-parsed citations/trace."""
    d = _to_iso(dict(row))
    d["citations"] = json.loads(d.get("citations") or "[]")
    d["trace"] = json.loads(d.get("trace") or "[]")
    return d


def add_review_item(conversation_id, query, draft_answer, agent_type=None,
                    citations=None, trace=None, confidence=None, reason=""):
    """Insert a review_queue row; returns the row as dict (_to_iso + parsed JSON on read)."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO review_queue
           (conversation_id, query, draft_answer, agent_type, citations, trace,
            confidence, reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            conversation_id,
            query,
            draft_answer,
            agent_type,
            json.dumps(citations or []),
            json.dumps(trace or []),
            confidence,
            reason,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM review_queue WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    conn.close()
    return _review_row(row)


def list_review_items(status: str | None = "pending") -> list[dict]:
    """Newest first. status=None returns all. JSON-parse citations/trace per row."""
    conn = get_db()
    if status is None:
        rows = conn.execute(
            "SELECT * FROM review_queue ORDER BY id DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM review_queue WHERE status = ? ORDER BY id DESC",
            (status,),
        ).fetchall()
    conn.close()
    return [_review_row(r) for r in rows]


def get_review_item(review_id: int) -> dict | None:
    """Single row with parsed JSON fields or None."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM review_queue WHERE id = ?", (review_id,)
    ).fetchone()
    conn.close()
    return _review_row(row) if row else None


def set_review_status(review_id: int, status: str, edited_answer: str | None = None) -> bool:
    """Update status (+edited_answer when provided) and bump updated_at. Returns False when no row matched.

    Edited-answer semantics: edited_answer is only overwritten when a new value is
    given (CASE keeps the previous value when the param is NULL), so approving or
    rejecting later never wipes an earlier human edit.
    """
    conn = get_db()
    cur = conn.execute(
        """UPDATE review_queue
           SET status = ?, updated_at = datetime('now'),
               edited_answer = CASE WHEN ? IS NULL THEN edited_answer ELSE ? END
           WHERE id = ?""",
        (status, edited_answer, edited_answer, review_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# Auto-init on import
init_db()


# ---- Regulatory Radar feed repository ----


def list_regulatory_items(limit: int = 100) -> list[dict]:
    """Newest fetched regulatory items first."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM regulatory_feed ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [_to_iso(dict(r)) for r in rows]


def get_regulatory_item(source_key: str, external_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM regulatory_feed WHERE source_key = ? AND external_id = ?",
        (source_key, external_id),
    ).fetchone()
    conn.close()
    return _to_iso(dict(row)) if row else None


def upsert_regulatory_item(
    source_key: str,
    external_id: str,
    regulator: str,
    kind: str,
    title: str,
    url: str,
    issued_at: str | None = None,
) -> dict:
    """Insert an item if new, otherwise return the existing row unchanged."""
    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM regulatory_feed WHERE source_key = ? AND external_id = ?",
        (source_key, external_id),
    ).fetchone()
    if existing:
        conn.close()
        return _to_iso(dict(existing))
    cur = conn.execute(
        """INSERT INTO regulatory_feed
           (source_key, external_id, regulator, kind, title, url, issued_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (source_key, external_id, regulator, kind, title, url, issued_at),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM regulatory_feed WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    conn.close()
    return _to_iso(dict(row))


def update_regulatory_item_status(
    item_id: int,
    status: str,
    chunks: int | None = None,
    summary: str | None = None,
) -> bool:
    conn = get_db()
    cur = conn.execute(
        """UPDATE regulatory_feed
           SET status = ?,
               chunks = COALESCE(?, chunks),
               summary = CASE WHEN ? IS NULL THEN summary ELSE ? END,
               fetched_at = datetime('now')
           WHERE id = ?""",
        (status, chunks, summary, summary, item_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0
