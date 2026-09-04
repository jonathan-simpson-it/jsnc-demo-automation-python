"""Immutable audit trail for regulatory compliance.

HKMA and SFC require firms to demonstrate who asked what, when,
and what the system answered. This module provides:
- Tamper-evident logging via hash chaining
- Query/response recording with user attribution
- Regulator-ready export
- Integrity verification
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone


class AuditLog:
    """Immutable audit trail backed by SQLite with hash-chain integrity."""

    def __init__(self, db_path: str = "./data/audit.db"):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None or not isinstance(conn, sqlite3.Connection):
            conn = sqlite3.connect(self.db_path, timeout=5)
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return conn

    def _init_db(self) -> None:
        conn = self._conn()
        conn.execute(
            """CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                query TEXT NOT NULL,
                response TEXT NOT NULL,
                agent_type TEXT NOT NULL,
                trace TEXT NOT NULL,
                user_id TEXT NOT NULL,
                confidence REAL,
                prev_hash TEXT,
                entry_hash TEXT NOT NULL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_timestamp ON audit_log(timestamp)"
        )
        conn.commit()

    def _compute_hash(self, entry: dict, prev_hash: str) -> str:
        """Compute SHA-256 hash of entry + previous hash for tamper evidence."""
        content = json.dumps(entry, sort_keys=True, default=str) + prev_hash
        return hashlib.sha256(content.encode()).hexdigest()

    def log_query(
        self,
        query: str,
        response: str,
        agent_type: str,
        trace: list[dict],
        user_id: str,
        confidence: float,
        document_ids: list[str] | None = None,
    ) -> int:
        """Log a query-response pair with tamper-evident hash chain."""
        conn = self._conn()
        timestamp = datetime.now(timezone.utc).isoformat()

        # Get previous hash for chain
        row = conn.execute(
            "SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_hash = row[0] if row else ""

        entry = {
            "timestamp": timestamp,
            "query": query,
            "response": response[:2000],
            "agent_type": agent_type,
            "trace": trace,
            "user_id": user_id,
            "confidence": confidence,
            "document_ids": document_ids or [],
        }
        entry_hash = self._compute_hash(entry, prev_hash)

        conn.execute(
            """INSERT INTO audit_log
               (timestamp, query, response, agent_type, trace, user_id,
                confidence, prev_hash, entry_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                timestamp,
                query,
                response[:2000],
                agent_type,
                json.dumps(trace, default=str),
                user_id,
                confidence,
                prev_hash,
                entry_hash,
            ),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def query_history(
        self,
        user_id: str | None = None,
        agent_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query audit history with optional filters."""
        conn = self._conn()
        conditions = []
        params = []
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if agent_type:
            conditions.append("agent_type = ?")
            params.append(agent_type)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = conn.execute(
            f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT ?",
            params + [limit],
        ).fetchall()

        return [
            {
                "id": r[0],
                "timestamp": r[1],
                "query": r[2],
                "response": r[3],
                "agent_type": r[4],
                "trace": json.loads(r[5]),
                "user_id": r[6],
                "confidence": r[7],
                "entry_hash": r[9],
            }
            for r in rows
        ]

    def export_for_regulator(self, format: str = "text") -> str:
        """Export audit trail in regulator-ready format."""
        history = self.query_history(limit=1000)
        lines = [
            "=" * 60,
            "PE AI SYSTEM: AUDIT TRAIL EXPORT",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            f"Total entries: {len(history)}",
            "=" * 60,
            "",
        ]
        for entry in history:
            lines.append(f"Entry #{entry['id']}")
            lines.append(f"  Timestamp: {entry['timestamp']}")
            lines.append(f"  User: {entry['user_id']}")
            lines.append(f"  Agent: {entry['agent_type']}")
            lines.append(f"  Query: {entry['query']}")
            lines.append(f"  Response: {entry['response'][:500]}")
            lines.append(f"  Confidence: {entry['confidence']}")
            lines.append(f"  Hash: {entry['entry_hash'][:16]}...")
            lines.append("")
        return "\n".join(lines)

    def verify_integrity(self) -> bool:
        """Verify the hash chain is unbroken (tamper detection)."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT prev_hash, entry_hash, query, response, agent_type, "
            "user_id, confidence, trace, timestamp FROM audit_log ORDER BY id"
        ).fetchall()

        prev = ""
        for row in rows:
            entry = {
                "timestamp": row[8],
                "query": row[2],
                "response": row[3],
                "agent_type": row[4],
                "trace": json.loads(row[7]),
                "user_id": row[5],
                "confidence": row[6],
                "document_ids": [],
            }
            expected_hash = self._compute_hash(entry, prev)
            if expected_hash != row[1]:
                return False
            prev = row[1]
        return True
