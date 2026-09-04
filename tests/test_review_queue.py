"""Tests for the review_queue repository.

Sandbox note: pytest/fastapi deps are not installed in this sandbox; the suite
runs in CI/venv.
"""

from pathlib import Path

import pytest

from src.core import database as db


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point every repository call at a throwaway SQLite file."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    # Re-run init so the schema (incl. review_queue) exists on the temp DB.
    db.init_db()
    yield tmp_path / "test.db"


def test_add_and_list_pending(isolated_db):
    item = db.add_review_item(
        7,
        "What is the liquidation preference?",
        "The liquidation preference is 1x.",
        agent_type="term_sheet",
        citations=["[Source 1: x.pdf, page 1, line 2]"],
        trace=[{"node": "draft", "ms": 42}],
        confidence=0.9,
        reason="drafted by agent",
    )
    assert item["id"] > 0
    assert item["status"] == "pending"
    assert item["citations"] == ["[Source 1: x.pdf, page 1, line 2]"]
    assert item["trace"] == [{"node": "draft", "ms": 42}]
    assert item["confidence"] == 0.9
    assert item["reason"] == "drafted by agent"
    assert item["created_at"].endswith("Z")

    pending = db.list_review_items()
    assert pending[0]["id"] == item["id"]
    assert pending[0]["query"] == "What is the liquidation preference?"
    assert pending[0]["draft_answer"] == "The liquidation preference is 1x."

    approved = db.list_review_items("approved")
    assert approved == []


def test_status_roundtrip(isolated_db):
    item = db.add_review_item(None, "q", "draft")
    assert db.set_review_status(item["id"], "approved") is True
    fetched = db.get_review_item(item["id"])
    assert fetched["status"] == "approved"
    assert db.set_review_status(item["id"], "rejected") is True
    assert db.get_review_item(item["id"])["status"] == "rejected"
    assert db.set_review_status(99999, "approved") is False


def test_edited_answer_preserved(isolated_db):
    item = db.add_review_item(None, "q", "draft")
    assert db.set_review_status(item["id"], "edited", "Edited text") is True
    fetched = db.get_review_item(item["id"])
    assert fetched["status"] == "edited"
    assert fetched["edited_answer"] == "Edited text"

    assert db.set_review_status(item["id"], "approved") is True
    fetched = db.get_review_item(item["id"])
    assert fetched["status"] == "approved"
    assert fetched["edited_answer"] == "Edited text"


def test_missing_item_returns_none(isolated_db):
    assert db.get_review_item(99999) is None


# ---------------------------------------------------------------------------
# Queueing policy through the agent routes (P3T2)
# ---------------------------------------------------------------------------

from src.core.models import AgentResponse
import src.api.routes.agents as _agents_mod
from src.api.main import app as _app
from fastapi.testclient import TestClient
from config.settings import settings


class _FakeRouter:
    def __init__(self, response: AgentResponse):
        self._r = response

    def invoke(self, query, agent_type=None, conversation_history=None,
               allowed_filenames=None):
        return self._r

    def invoke_streaming(self, query, agent_type=None, conversation_history=None,
                         allowed_filenames=None):
        yield {"node": "answer", "update": {}, "done": False}
        yield {"done": True, "response": self._r}


def _make_response(confidence: float, rescue: bool) -> AgentResponse:
    trace = [{"node": "answer", "ms": 1}]
    if rescue:
        trace.append({"node": "verify", "ms": 1})
    return AgentResponse(
        agent_type="due_diligence",
        result='{"summary":"x"}',
        citations=[],
        confidence_score=confidence,
        metadata={"trace": trace},
    )


def _make_conversation(client, monkeypatch, response):
    monkeypatch.setattr(_agents_mod, "get_router_agent",
                        lambda: _FakeRouter(response))
    conv = client.post("/api/conversations", json={"project_id": None}).json()
    return conv["id"]


def _cleanup(client, conv_id):
    client.delete(f"/api/conversations/{conv_id}")


def test_low_confidence_queues_not_persisted(isolated_db, monkeypatch):
    monkeypatch.setattr(settings, "enable_human_review", False)
    client = TestClient(_app)
    conv_id = _make_conversation(
        client, monkeypatch, _make_response(0.4, rescue=True))
    try:
        resp = client.post("/api/agents/execute", json={
            "query": "Is this risky?",
            "agent_type": "due_diligence",
            "conversation_id": conv_id,
        })
        assert resp.status_code == 200
        meta = resp.json()["metadata"]
        assert meta["review"]["status"] == "pending"
        items = db.list_review_items()
        assert items and items[0]["conversation_id"] == conv_id
        assert "low_confidence" in items[0]["reason"]
        msgs = client.get(f"/api/conversations/{conv_id}/messages").json()["messages"]
        assert len(msgs) == 1 and msgs[0]["role"] == "user"
    finally:
        _cleanup(client, conv_id)


def test_high_confidence_persists_not_queued(isolated_db, monkeypatch):
    monkeypatch.setattr(settings, "enable_human_review", False)
    client = TestClient(_app)
    conv_id = _make_conversation(
        client, monkeypatch, _make_response(0.9, rescue=False))
    try:
        resp = client.post("/api/agents/execute", json={
            "query": "What is the valuation?",
            "agent_type": "due_diligence",
            "conversation_id": conv_id,
        })
        assert resp.status_code == 200
        assert "review" not in resp.json()["metadata"]
        assert db.list_review_items() == []
        msgs = client.get(f"/api/conversations/{conv_id}/messages").json()["messages"]
        assert len(msgs) == 2
    finally:
        _cleanup(client, conv_id)


def test_human_review_flag_queues_everything(isolated_db, monkeypatch):
    monkeypatch.setattr(settings, "enable_human_review", True)
    client = TestClient(_app)
    conv_id = _make_conversation(
        client, monkeypatch, _make_response(0.9, rescue=False))
    try:
        resp = client.post("/api/agents/execute", json={
            "query": "Generate the LP report.",
            "agent_type": "lp_report",
            "conversation_id": conv_id,
        })
        assert resp.status_code == 200
        assert resp.json()["metadata"]["review"]["status"] == "pending"
        items = db.list_review_items()
        assert items and "human review enabled" in items[0]["reason"]
    finally:
        _cleanup(client, conv_id)


def test_stream_low_confidence_queues(isolated_db, monkeypatch):
    monkeypatch.setattr(settings, "enable_human_review", False)
    client = TestClient(_app)
    conv_id = _make_conversation(
        client, monkeypatch, _make_response(0.35, rescue=True))
    try:
        with client.stream("POST", "/api/agents/execute/stream", json={
            "query": "Check compliance.",
            "agent_type": "compliance",
            "conversation_id": conv_id,
        }) as r:
            assert r.status_code == 200
            body = "".join(r.iter_text())
        assert '"review"' in body
        assert db.list_review_items()  # queued
        msgs = client.get(f"/api/conversations/{conv_id}/messages").json()["messages"]
        assert len(msgs) == 1 and msgs[0]["role"] == "user"
    finally:
        _cleanup(client, conv_id)


# ---------------------------------------------------------------------------
# Review endpoints (P3T3)
# ---------------------------------------------------------------------------


def test_error_answer_never_queues(isolated_db, monkeypatch):
    """A failed turn (bad key, outage) surfaces immediately: never queued,
    even when human review is enabled, and persisted as an error message."""
    monkeypatch.setattr(settings, "enable_human_review", True)
    client = TestClient(_app)
    error_resp = AgentResponse(
        agent_type="due_diligence",
        result="Error: Error code: 401 - invalid api key",
        citations=[],
        confidence_score=0.0,
        metadata={"trace": [], "error": True},
    )
    conv_id = _make_conversation(client, monkeypatch, error_resp)
    try:
        resp = client.post("/api/agents/execute", json={
            "query": "Hello?",
            "agent_type": "due_diligence",
            "conversation_id": conv_id,
        })
        assert resp.status_code == 200
        assert "review" not in resp.json()["metadata"]
        assert db.list_review_items() == []
        msgs = client.get(
            f"/api/conversations/{conv_id}/messages"
        ).json()["messages"]
        assert len(msgs) == 2 and msgs[1]["role"] == "assistant"
        assert msgs[1]["is_error"] == 1
    finally:
        _cleanup(client, conv_id)


def test_approve_appends_to_conversation(isolated_db, monkeypatch):
    client = TestClient(_app)
    conv_id = client.post(
        "/api/conversations", json={"project_id": None}
    ).json()["id"]
    item = db.add_review_item(
        conv_id, "q", "draft", agent_type="due_diligence",
        citations=["[Source 1: x.pdf, page 1, line 2]"],
        trace=[{"node": "verify", "ms": 1}], confidence=0.3,
        reason="test",
    )
    try:
        resp = client.post(f"/api/review/{item['id']}/approve", json={})
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
        msgs = client.get(
            f"/api/conversations/{conv_id}/messages"
        ).json()["messages"]
        assert len(msgs) == 1 and msgs[0]["role"] == "assistant"
        assert msgs[0]["content"] == "draft"
    finally:
        client.delete(f"/api/conversations/{conv_id}")


def test_approve_with_edit(isolated_db):
    client = TestClient(_app)
    conv_id = client.post(
        "/api/conversations", json={"project_id": None}
    ).json()["id"]
    item = db.add_review_item(conv_id, "q", "draft")
    try:
        resp = client.post(
            f"/api/review/{item['id']}/approve",
            json={"answer": "Edited"},
        )
        assert resp.json()["status"] == "edited"
        assert db.get_review_item(item["id"])["edited_answer"] == "Edited"
        msgs = client.get(
            f"/api/conversations/{conv_id}/messages"
        ).json()["messages"]
        assert msgs[-1]["content"] == "Edited"
    finally:
        client.delete(f"/api/conversations/{conv_id}")


def test_reject_adds_nothing(isolated_db):
    client = TestClient(_app)
    conv_id = client.post(
        "/api/conversations", json={"project_id": None}
    ).json()["id"]
    item = db.add_review_item(conv_id, "q", "draft")
    try:
        resp = client.post(f"/api/review/{item['id']}/reject")
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"
        msgs = client.get(
            f"/api/conversations/{conv_id}/messages"
        ).json()["messages"]
        assert msgs == []
    finally:
        client.delete(f"/api/conversations/{conv_id}")


def test_endpoint_404s(isolated_db):
    client = TestClient(_app)
    assert client.post("/api/review/99999/approve", json={}).status_code == 404
    assert client.post("/api/review/99999/reject").status_code == 404
