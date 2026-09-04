"""API tests for graph mail routes (offline/demo paths)."""

from fastapi.testclient import TestClient

from src.api.main import app
from src.compliance.summary import SummaryGenerator


def _fake_summary(*args, **kwargs):
    return {
        "total_queries": 3,
        "avg_confidence": 0.8,
        "agent_breakdown": [{"agent": "due_diligence", "count": 3, "pct": 100.0}],
        "top_queries": [
            {
                "query": "Risks?",
                "agent": "due_diligence",
                "confidence": 0.8,
                "timestamp": "2026-09-01T00:00:00",
            }
        ],
        "user_activity": [{"user": "local", "queries": 3}],
    }


def test_generate_returns_template_without_key(monkeypatch):
    monkeypatch.setattr(SummaryGenerator, "generate", _fake_summary)
    client = TestClient(app)
    res = client.post(
        "/api/graph/mail/draft/generate",
        json={"period": "week", "template": "digest"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["generated_by"] == "template"
    assert body["subject"]
    assert "due_diligence" in body["body"]


def test_drafts_demo_roundtrip_via_api(monkeypatch, tmp_path):
    import src.graph_mail as gm

    monkeypatch.setattr(gm, "configured", lambda: False)
    monkeypatch.setattr(gm, "DEMO_DB_PATH", str(tmp_path / "d.db"))
    client = TestClient(app)
    assert (
        client.post(
            "/api/graph/mail/drafts", json={"subject": "s", "body": "b"}
        ).status_code
        == 200
    )
    drafts = client.get("/api/graph/mail/drafts").json()["drafts"]
    assert len(drafts) == 1 and drafts[0]["subject"] == "s"


def test_draft_content_type_validation():
    client = TestClient(app)
    res = client.post(
        "/api/graph/mail/drafts",
        json={"subject": "s", "body": "b", "content_type": "video"},
    )
    assert res.status_code == 400
