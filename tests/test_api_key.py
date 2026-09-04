import pytest
from src.utils.api_key import (
    ApiKeyMissingError,
    get_request_api_key,
    reset_request_api_key,
    resolve_api_key,
    set_request_api_key,
)


def test_resolve_prefers_request_key_over_settings(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "deepseek_api_key", "env-key")
    token = set_request_api_key("user-key")
    try:
        assert resolve_api_key() == "user-key"
    finally:
        reset_request_api_key(token)


def test_resolve_falls_back_to_settings_key(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "deepseek_api_key", "env-key")
    token = set_request_api_key(None)
    try:
        assert resolve_api_key() == "env-key"
    finally:
        reset_request_api_key(token)


def test_resolve_raises_when_no_key_anywhere(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    token = set_request_api_key(None)
    try:
        with pytest.raises(ApiKeyMissingError):
            resolve_api_key()
    finally:
        reset_request_api_key(token)


def test_request_key_resets_cleanly():
    token = set_request_api_key("abc")
    reset_request_api_key(token)
    assert get_request_api_key() is None


def test_make_llm_uses_request_key(monkeypatch):
    captured = {}
    import src.agents.graph as graph

    class FakeChatDeepSeek:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(graph, "ChatDeepSeek", FakeChatDeepSeek)
    token = set_request_api_key("req-key-123")
    try:
        graph._make_llm(temperature=0.5)
    finally:
        reset_request_api_key(token)
    assert captured["api_key"] == "req-key-123"
    assert captured["temperature"] == 0.5


from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.api.key_middleware import ApiKeyContextMiddleware


def _capture_app():
    inner = FastAPI()
    seen = {}

    @inner.get("/probe")
    async def probe():
        seen["key"] = get_request_api_key()
        return {"ok": True}

    wrapped = ApiKeyContextMiddleware(inner)
    test_app = FastAPI()
    test_app.mount("/", wrapped)
    return TestClient(test_app), seen


def test_middleware_sets_request_key():
    client, seen = _capture_app()
    client.get("/probe", headers={"X-API-Key": "  user-key-1  "})
    assert seen["key"] == "user-key-1"


def test_middleware_leaves_context_clean_without_header():
    client, seen = _capture_app()
    client.get("/probe")
    assert seen["key"] is None


from config.settings import settings
from src.api.main import app


class _FakeRouter:
    """Stands in for RouterAgent; records the resolved key."""

    def __init__(self):
        self.seen_keys = []

    def invoke(self, **kwargs):
        self.seen_keys.append(_resolved())
        return _fake_response("answer", [])

    def invoke_streaming(self, **kwargs):
        self.seen_keys.append(_resolved())
        yield {"done": True, "response": _fake_response("answer", [])}


def _resolved():
    from src.utils.api_key import resolve_api_key
    return resolve_api_key()


def _fake_response(result, citations):
    from src.core.models import AgentResponse

    return AgentResponse(
        agent_type="due_diligence",
        result=result,
        citations=citations,
        confidence_score=0.9,
        metadata={"query": "hi", "trace": [], "routing_method": "forced"},
    )


def test_execute_returns_402_without_any_key(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    client = TestClient(app)
    res = client.post(
        "/api/agents/execute", json={"query": "hi", "agent_type": "due_diligence"}
    )
    assert res.status_code == 402
    assert res.json()["detail"]["code"] == "missing_api_key"


def test_stream_returns_402_without_any_key(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    client = TestClient(app)
    res = client.post(
        "/api/agents/execute/stream", json={"query": "hi", "agent_type": "due_diligence"}
    )
    assert res.status_code == 402
    assert res.json()["detail"]["code"] == "missing_api_key"


def test_request_key_reaches_router(monkeypatch):
    """Header key must flow: middleware -> contextvar -> endpoint -> router."""
    monkeypatch.setattr(settings, "deepseek_api_key", "env-key")
    fake = _FakeRouter()
    monkeypatch.setattr(
        "src.api.routes.agents.get_router_agent", lambda: fake
    )
    client = TestClient(app)
    res = client.post(
        "/api/agents/execute",
        json={"query": "hi", "agent_type": "due_diligence"},
        headers={"X-API-Key": "user-key-abc"},
    )
    assert res.status_code == 200
    assert fake.seen_keys == ["user-key-abc"]


def test_request_key_reaches_router_streaming(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "env-key")
    fake = _FakeRouter()
    monkeypatch.setattr(
        "src.api.routes.agents.get_router_agent", lambda: fake
    )
    client = TestClient(app)
    res = client.post(
        "/api/agents/execute/stream",
        json={"query": "hi", "agent_type": "due_diligence"},
        headers={"X-API-Key": "user-key-abc"},
    )
    assert res.status_code == 200
    assert fake.seen_keys == ["user-key-abc"]


def test_health_reports_server_key_state(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    client = TestClient(app)
    assert client.get("/health").json()["server_key_configured"] is False
    monkeypatch.setattr(settings, "deepseek_api_key", "env-key")
    assert client.get("/health").json()["server_key_configured"] is True
