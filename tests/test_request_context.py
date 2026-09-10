"""Request-ID correlation and structured 500 envelope tests."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.request_id_middleware import RequestContextMiddleware


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ok")
    async def ok():
        return {"status": "ok"}

    @app.get("/boom")
    async def boom():
        raise ValueError("secret stack detail")

    return app


def test_response_gets_generated_request_id():
    client = TestClient(_make_app())
    res = client.get("/ok")
    assert res.status_code == 200
    assert res.headers.get("X-Request-ID")


def test_incoming_request_id_is_honoured():
    client = TestClient(_make_app())
    res = client.get("/ok", headers={"X-Request-ID": "abc-123"})
    assert res.headers.get("X-Request-ID") == "abc-123"


def test_unsafe_incoming_request_id_is_replaced():
    client = TestClient(_make_app())
    res = client.get("/ok", headers={"X-Request-ID": "bad\nX-Evil: 1"})
    assert res.headers.get("X-Request-ID")
    assert res.headers.get("X-Request-ID") != "bad\nX-Evil: 1"


def test_unhandled_error_returns_envelope_with_request_id():
    client = TestClient(_make_app())
    res = client.get("/boom")
    assert res.status_code == 500
    body = res.json()["detail"]
    assert body["code"] == "internal_error"
    assert body["message"] == "Internal server error"
    assert body["request_id"] == res.headers.get("X-Request-ID")
    assert "secret stack detail" not in res.text
