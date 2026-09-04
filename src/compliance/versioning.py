"""Model/version pinning and change tracking.

HKMA fintech guidelines typically require firms to freeze model versions
for a period and document any changes. This module tracks which model
version was used for each query and records configuration changes.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone


class ModelVersionTracker:
    """Track model versions and configuration changes."""

    def __init__(self, db_path: str = "./data/model_versions.db"):
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
            """CREATE TABLE IF NOT EXISTS model_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                model_name TEXT NOT NULL,
                version TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                notes TEXT
            )"""
        )
        conn.commit()

    def register(
        self,
        model_name: str,
        version: str,
        config_hash: str,
        notes: str = "",
    ) -> None:
        """Register a model version deployment."""
        conn = self._conn()
        timestamp = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO model_versions
               (timestamp, model_name, version, config_hash, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (timestamp, model_name, version, config_hash, notes),
        )
        conn.commit()

    def get_current(self) -> dict | None:
        """Get the most recent model version."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM model_versions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "timestamp": row[1],
            "model_name": row[2],
            "version": row[3],
            "config_hash": row[4],
            "notes": row[5],
        }

    def get_history(self, model_name: str | None = None, limit: int = 50) -> list[dict]:
        """Get version history, optionally filtered by model name."""
        conn = self._conn()
        if model_name:
            rows = conn.execute(
                "SELECT * FROM model_versions WHERE model_name = ? ORDER BY id DESC LIMIT ?",
                (model_name, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM model_versions ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "timestamp": r[1],
                "model_name": r[2],
                "version": r[3],
                "config_hash": r[4],
                "notes": r[5],
            }
            for r in rows
        ]

    @staticmethod
    def compute_config_hash(config: dict) -> str:
        """Compute a hash of the system configuration for change detection."""
        content = json.dumps(config, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
