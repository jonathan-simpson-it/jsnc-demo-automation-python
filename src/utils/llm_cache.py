"""Persistent LLM response cache backed by SQLite.

Avoids redundant API calls for repeated queries and classification.
Uses a SQLite database with TTL expiry and LRU eviction so the cache
survives process restarts — useful for the eval harness (--retry-failed)
and multi-instance deployments.
"""

import hashlib
import json
import sqlite3
import threading
import time
from typing import Any

_DEFAULT_DB = "./data/llm_cache.db"


class LLMCache:
    """SQLite-backed TTL cache for LLM responses."""

    def __init__(
        self,
        db_path: str = _DEFAULT_DB,
        ttl_seconds: int = 3600,
        max_size: int = 500,
    ):
        self.db_path = db_path
        self.ttl = ttl_seconds
        self.max_size = max_size
        self._local = threading.local()
        self._init_db()

    # -- connection helpers (one per thread) --------------------------------

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
            """CREATE TABLE IF NOT EXISTS cache (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                timestamp   REAL NOT NULL,
                access_count INTEGER DEFAULT 0
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ts ON cache(timestamp)"
        )
        conn.commit()

    # -- key helper ---------------------------------------------------------

    @staticmethod
    def _make_key(query: str, prefix: str = "") -> str:
        raw = f"{prefix}:{query.strip().lower()}"
        return hashlib.md5(raw.encode()).hexdigest()

    # -- public API (same interface as the old in-memory cache) -------------

    def get(self, query: str, prefix: str = "") -> Any | None:
        key = self._make_key(query, prefix)
        conn = self._conn()
        row = conn.execute(
            "SELECT value, timestamp FROM cache WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        value_str, ts = row
        if time.time() - ts >= self.ttl:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()
            return None
        # Touch timestamp on access for LRU eviction ordering
        conn.execute(
            "UPDATE cache SET timestamp = ?, access_count = access_count + 1 "
            "WHERE key = ?",
            (time.time(), key),
        )
        conn.commit()
        try:
            return json.loads(value_str)
        except (json.JSONDecodeError, TypeError):
            return value_str

    def set(self, query: str, value: Any, prefix: str = "") -> None:
        key = self._make_key(query, prefix)
        serialized = json.dumps(value, default=str)
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, timestamp, access_count) "
            "VALUES (?, ?, ?, 0)",
            (key, serialized, time.time()),
        )
        conn.commit()
        self._evict()

    def invalidate(self, query: str, prefix: str = "") -> None:
        key = self._make_key(query, prefix)
        conn = self._conn()
        conn.execute("DELETE FROM cache WHERE key = ?", (key,))
        conn.commit()

    def clear(self) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM cache")
        conn.commit()

    @property
    def size(self) -> int:
        conn = self._conn()
        row = conn.execute("SELECT COUNT(*) FROM cache").fetchone()
        return row[0] if row else 0

    # -- eviction -----------------------------------------------------------

    def _evict(self) -> None:
        conn = self._conn()
        count = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        if count <= self.max_size:
            return
        excess = count - self.max_size
        # Evict least recently used (oldest timestamp)
        conn.execute(
            "DELETE FROM cache WHERE key IN "
            "(SELECT key FROM cache ORDER BY timestamp ASC LIMIT ?)",
            (excess,),
        )
        conn.commit()


def _make_global_cache() -> LLMCache:
    try:
        from config.settings import settings
        db = settings.cache_db_path
    except Exception:
        db = _DEFAULT_DB
    return LLMCache(db_path=db, ttl_seconds=3600, max_size=500)


# Global cache instance
llm_cache = _make_global_cache()
