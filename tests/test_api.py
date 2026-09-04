"""Tests for FastAPI backend."""

from fastapi.testclient import TestClient
from src.api.main import app


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_agents_endpoint():
    response = client.get("/api/agents")
    assert response.status_code == 200
    data = response.json()
    assert "agents" in data
    assert len(data["agents"]) == 5


def test_document_stats_endpoint():
    response = client.get("/api/documents/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_documents" in data
