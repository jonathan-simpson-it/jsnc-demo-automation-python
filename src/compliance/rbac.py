"""Role-based access control with document-level permissions.

Not just 'who can query' but 'who can query which documents.'
A junior analyst shouldn't query LP-only fund performance data.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone


# Default role permissions
_DEFAULT_ROLES = {
    "admin": ["read_all", "query", "upload", "delete", "manage_users"],
    "senior_analyst": ["read_all", "query", "upload"],
    "analyst": ["read_all", "query"],
    "junior_analyst": ["read_limited", "query"],
    "viewer": ["read_limited"],
}


class RBACManager:
    """Role-based access control with document-level permissions."""

    def __init__(self, db_path: str = "./data/rbac.db"):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()
        self._seed_defaults()

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
            """CREATE TABLE IF NOT EXISTS roles (
                name TEXT PRIMARY KEY,
                permissions TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS user_roles (
                user_id TEXT NOT NULL,
                role_name TEXT NOT NULL,
                assigned_at TEXT NOT NULL,
                PRIMARY KEY (user_id, role_name)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS document_access (
                user_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                granted_at TEXT NOT NULL,
                PRIMARY KEY (user_id, document_id)
            )"""
        )
        conn.commit()

    def _seed_defaults(self) -> None:
        conn = self._conn()
        now = datetime.now(timezone.utc).isoformat()
        for role, perms in _DEFAULT_ROLES.items():
            conn.execute(
                "INSERT OR IGNORE INTO roles (name, permissions, created_at) VALUES (?, ?, ?)",
                (role, json.dumps(perms), now),
            )
        conn.commit()

    def create_role(self, name: str, permissions: list[str]) -> None:
        conn = self._conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO roles (name, permissions, created_at) VALUES (?, ?, ?)",
            (name, json.dumps(permissions), now),
        )
        conn.commit()

    def list_roles(self) -> list[str]:
        conn = self._conn()
        rows = conn.execute("SELECT name FROM roles").fetchall()
        return [r[0] for r in rows]

    def assign_role(self, user_id: str, role_name: str) -> None:
        conn = self._conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO user_roles (user_id, role_name, assigned_at) VALUES (?, ?, ?)",
            (user_id, role_name, now),
        )
        conn.commit()

    def get_user_roles(self, user_id: str) -> list[str]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT role_name FROM user_roles WHERE user_id = ?", (user_id,)
        ).fetchall()
        return [r[0] for r in rows]

    def check_permission(self, user_id: str, permission: str) -> bool:
        """Check if user has a specific permission via any of their roles."""
        roles = self.get_user_roles(user_id)
        if not roles:
            return False
        conn = self._conn()
        for role in roles:
            row = conn.execute(
                "SELECT permissions FROM roles WHERE name = ?", (role,)
            ).fetchone()
            if row:
                perms = json.loads(row[0])
                if permission in perms:
                    return True
        return False

    def grant_document_access(self, user_id: str, document_id: str) -> None:
        conn = self._conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO document_access (user_id, document_id, granted_at) VALUES (?, ?, ?)",
            (user_id, document_id, now),
        )
        conn.commit()

    def check_document_access(self, user_id: str, document_id: str) -> bool:
        """Check if user can access a specific document."""
        # Admin/senior_analyst with read_all can access everything
        roles = self.get_user_roles(user_id)
        conn = self._conn()
        for role in roles:
            row = conn.execute(
                "SELECT permissions FROM roles WHERE name = ?", (role,)
            ).fetchone()
            if row and "read_all" in json.loads(row[0]):
                return True
        conn = self._conn()
        row = conn.execute(
            "SELECT 1 FROM document_access WHERE user_id = ? AND document_id = ?",
            (user_id, document_id),
        ).fetchone()
        return row is not None

    def list_accessible_documents(self, user_id: str) -> list[str]:
        """List documents the user can access."""
        if self.check_permission(user_id, "read_all"):
            return ["*"]  # All documents
        conn = self._conn()
        rows = conn.execute(
            "SELECT document_id FROM document_access WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        return [r[0] for r in rows]
