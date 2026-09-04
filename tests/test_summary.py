"""Tests for email summary generator."""

import tempfile
from datetime import datetime, timezone, timedelta

from src.compliance.audit import AuditLog
from src.compliance.summary import SummaryGenerator


def _seed_audit(db_path: str, count: int = 5) -> None:
    """Seed the audit log with sample entries."""
    audit = AuditLog(db_path=db_path)
    agents = ["due_diligence", "term_sheet", "compliance", "lp_report", "cross_doc"]
    users = ["analyst_001", "analyst_002", "admin_001"]
    for i in range(count):
        audit.log_query(
            query=f"What is the risk level for deal {i}?",
            response=f"Deal {i} has moderate risk.",
            agent_type=agents[i % len(agents)],
            trace=[{"node": "classify", "ms": 5}, {"node": "search", "ms": 100}],
            user_id=users[i % len(users)],
            confidence=0.85 + (i * 0.02),
        )


def test_generate_week_summary():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/audit.db"
        _seed_audit(db_path, count=5)

        gen = SummaryGenerator(db_path=db_path)
        result = gen.generate(period="week")

        assert result["period"] == "week"
        assert result["period_label"] == "Last 7 Days"
        assert result["total_queries"] == 5
        assert result["avg_confidence"] > 0
        assert len(result["agent_breakdown"]) > 0
        assert len(result["user_activity"]) > 0
        assert len(result["top_queries"]) > 0
        assert "PE AI System" in result["email_markdown"]
        assert "Total Queries" in result["email_markdown"]


def test_generate_month_summary():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/audit.db"
        _seed_audit(db_path, count=3)

        gen = SummaryGenerator(db_path=db_path)
        result = gen.generate(period="month")

        assert result["period"] == "month"
        assert result["period_label"] == "Last 30 Days"
        assert result["total_queries"] == 3


def test_empty_summary():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/audit.db"
        platform_path = f"{tmpdir}/platform.db"  # no chat history either
        gen = SummaryGenerator(db_path=db_path, platform_db_path=platform_path)
        result = gen.generate(period="week")

        assert result["total_queries"] == 0
        assert result["avg_confidence"] == 0.0
        assert len(result["agent_breakdown"]) == 0
        assert "No data yet" not in result["email_markdown"]


def test_falls_back_to_chat_history_when_audit_empty():
    """Empty audit + real chat history => report reflects the chats."""
    import sqlite3

    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = f"{tmpdir}/audit.db"
        platform_path = f"{tmpdir}/platform.db"
        conn = sqlite3.connect(platform_path)
        conn.execute(
            """CREATE TABLE conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                agent_type TEXT,
                citations TEXT,
                trace TEXT,
                confidence REAL,
                is_error INTEGER DEFAULT 0,
                created_at TEXT
            )"""
        )
        conn.executemany(
            "INSERT INTO conversation_messages "
            "(conversation_id, role, content, agent_type, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, "user", "What is the deal risk?", None, None, "2026-09-02 10:00:00"),
                (1, "assistant", "Moderate risk.", "due_diligence", 0.9, "2026-09-02 10:00:05"),
                (1, "user", "Compare the decks", None, None, "2026-09-01 09:00:00"),
                (1, "assistant", "Differences found.", "cross_doc", 0.8, "2026-09-01 09:00:03"),
            ],
        )
        conn.commit()
        conn.close()

        gen = SummaryGenerator(db_path=audit_path, platform_db_path=platform_path)
        result = gen.generate(period="week")

        assert result["total_queries"] == 2
        agents = {a["agent"] for a in result["agent_breakdown"]}
        assert agents == {"due_diligence", "cross_doc"}
        assert result["top_queries"][0]["query"] == "What is the deal risk?"


def test_email_markdown_format():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/audit.db"
        _seed_audit(db_path, count=3)

        gen = SummaryGenerator(db_path=db_path)
        result = gen.generate(period="week")

        md = result["email_markdown"]
        assert "# PE AI System" in md
        assert "## Key Metrics" in md
        assert "## Agent Usage" in md
        assert "## User Activity" in md
        assert "## Recent Queries" in md
        assert "audit trail" in md.lower()
