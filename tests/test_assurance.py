"""Tests for the compliance assurance-pack endpoint."""

import functools
import sqlite3

from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes.assurance import build_assurance_pack
from src.compliance.audit import AuditLog
from src.compliance.versioning import ModelVersionTracker

client = TestClient(app)


def _make_stores(tmpdir):
    """Fresh audit + version stores with one entry each."""
    audit = AuditLog(db_path=f"{tmpdir}/audit.db")
    audit.log_query(
        query="What is the liquidation preference?",
        response="1x non-participating preferred",
        agent_type="term_sheet",
        trace=[{"node": "classify", "ms": 5}, {"node": "search", "ms": 100}],
        user_id="analyst_001",
        confidence=0.92,
    )
    tracker = ModelVersionTracker(db_path=f"{tmpdir}/versions.db")
    tracker.register(
        model_name="deepseek-chat",
        version="1.0.0",
        config_hash="abc123",
        notes="Initial deployment",
    )
    return audit, tracker


def test_pack_contains_all_sections(tmp_path):
    audit, tracker = _make_stores(tmp_path)
    pack = build_assurance_pack(audit=audit, tracker=tracker)

    assert pack.startswith("# Compliance Assurance Pack")
    assert "## 1. Audit Chain Integrity" in pack
    assert "VERIFIED" in pack
    assert "## 2. Model Versions" in pack
    assert "deepseek-chat v1.0.0" in pack
    assert "## 3. Explainability Report" in pack
    # The explainability section reuses the latest audited query
    assert "What is the liquidation preference?" in pack
    assert " PE AI SYSTEM: AUDIT TRAIL EXPORT " in pack or "AUDIT TRAIL EXPORT" in pack


def test_pack_tamper_detection(tmp_path):
    audit, tracker = _make_stores(tmp_path)
    # Tamper with a stored response after logging -> chain must not verify
    conn = sqlite3.connect(f"{tmp_path}/audit.db")
    conn.execute("UPDATE audit_log SET response = 'tampered' WHERE id = 1")
    conn.commit()
    conn.close()

    pack = build_assurance_pack(audit=audit, tracker=tracker)
    assert "FAILED" in pack


def test_pack_empty_stores_degrade_cleanly(tmp_path):
    audit = AuditLog(db_path=f"{tmp_path}/audit.db")
    tracker = ModelVersionTracker(db_path=f"{tmp_path}/versions.db")

    pack = build_assurance_pack(audit=audit, tracker=tracker)
    assert "VERIFIED" in pack  # empty trail is trivially intact
    assert "No audited queries yet" in pack
    assert "No model versions registered" in pack


def test_pack_endpoint_downloads_markdown(monkeypatch, tmp_path):
    audit, tracker = _make_stores(tmp_path)
    monkeypatch.setattr(
        "src.api.routes.assurance.build_assurance_pack",
        functools.partial(build_assurance_pack, audit=audit, tracker=tracker),
    )
    response = client.get("/api/assurance/pack")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="assurance-pack-'
    )
    assert "# Compliance Assurance Pack" in response.text


def test_manifest_endpoint():
    response = client.get("/api/assurance/manifest")
    assert response.status_code == 200
    data = response.json()
    assert data["download"] == "/api/assurance/pack"
    assert len(data["sections"]) == 3
