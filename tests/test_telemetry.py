"""Tests for telemetry run log + endpoints.

Sandbox note: requires the project venv/CI (pytest, fastapi, TestClient).
"""

import src.api.routes.agents as agents_mod
from src.api.main import app
from src.core.models import AgentResponse
from src.utils.telemetry import run_log
from fastapi.testclient import TestClient


class _FakeRouter:
    def __init__(self, response: AgentResponse):
        self._r = response

    def invoke(self, query, agent_type=None, conversation_history=None,
               allowed_filenames=None):
        return self._r


def test_run_pushed_on_execute(monkeypatch):
    run_log.reset()
    resp = AgentResponse(
        agent_type="due_diligence",
        result='{"summary":"ok"}',
        citations=[],
        confidence_score=0.9,
        metadata={
            "routing_method": "forced",
            "trace": [{"node": "search", "ms": 5}, {"node": "answer", "ms": 10}],
        },
    )
    monkeypatch.setattr(agents_mod, "get_router_agent",
                        lambda: _FakeRouter(resp))
    client = TestClient(app)
    r = client.post("/api/agents/execute",
                    json={"query": "valuation?", "agent_type": "due_diligence"})
    assert r.status_code == 200

    runs = run_log.all()
    assert len(runs) == 1
    run = runs[0]
    assert run["query"] == "valuation?"
    assert run["agent_type"] == "due_diligence"
    assert run["total_ms"] == 15
    assert run["error"] is False
    assert len(run["trace"]) == 2


def test_telemetry_endpoints(monkeypatch):
    run_log.reset()
    resp = AgentResponse(
        agent_type="term_sheet", result="{}", citations=[],
        confidence_score=0.9,
        metadata={"trace": [{"node": "answer", "ms": 1}], "routing_method": "forced"},
    )
    monkeypatch.setattr(agents_mod, "get_router_agent",
                        lambda: _FakeRouter(resp))
    client = TestClient(app)
    client.post("/api/agents/execute",
                json={"query": "extract", "agent_type": "term_sheet"})

    runs = client.get("/api/telemetry/runs").json()["runs"]
    assert len(runs) == 1
    assert runs[0]["agent_type"] == "term_sheet"
    # The fake router never reaches the graph, so no real LLM call is made;
    # cost accounting accrues only from genuine graph invocations.
    assert client.get("/api/telemetry/cost").json()["calls"] == 0

    reset = client.post("/api/telemetry/reset")
    assert reset.json()["reset"] is True
    assert client.get("/api/telemetry/runs").json()["runs"] == []
    assert client.get("/api/telemetry/cost").json()["calls"] == 0
