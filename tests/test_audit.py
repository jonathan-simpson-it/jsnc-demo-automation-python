"""Tests for immutable audit trail."""

import tempfile
from src.compliance.audit import AuditLog


def test_log_query():
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = AuditLog(db_path=f"{tmpdir}/audit.db")
        audit.log_query(
            query="What is the liquidation preference?",
            response="1x non-participating preferred",
            agent_type="term_sheet",
            trace=[{"node": "classify", "ms": 5}, {"node": "search", "ms": 100}],
            user_id="analyst_001",
            confidence=0.92,
        )
        history = audit.query_history()
        assert len(history) == 1
        assert history[0]["query"] == "What is the liquidation preference?"
        assert history[0]["user_id"] == "analyst_001"


def test_export_for_regulator():
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = AuditLog(db_path=f"{tmpdir}/audit.db")
        audit.log_query(
            query="Check SFC compliance",
            response="Compliant with SFC Guidelines",
            agent_type="compliance",
            trace=[],
            user_id="analyst_002",
            confidence=0.85,
        )
        export = audit.export_for_regulator()
        assert "Check SFC compliance" in export
        assert "analyst_002" in export
        assert "compliance" in export


def test_tamper_evidence():
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = AuditLog(db_path=f"{tmpdir}/audit.db")
        audit.log_query(query="test", response="answer", agent_type="dd", trace=[], user_id="u1", confidence=0.9)
        # Verify hash chain
        assert audit.verify_integrity() is True


def test_query_history_filter():
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = AuditLog(db_path=f"{tmpdir}/audit.db")
        audit.log_query(query="q1", response="a1", agent_type="term_sheet", trace=[], user_id="u1", confidence=0.9)
        audit.log_query(query="q2", response="a2", agent_type="compliance", trace=[], user_id="u2", confidence=0.8)
        # Filter by user
        history = audit.query_history(user_id="u1")
        assert len(history) == 1
        # Filter by agent type
        history2 = audit.query_history(agent_type="compliance")
        assert len(history2) == 1
