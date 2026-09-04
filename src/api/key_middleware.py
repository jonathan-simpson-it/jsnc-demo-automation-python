"""Middleware that stores the per-request X-API-Key in a contextvar."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.utils.api_key import (
    API_KEY_HEADER,
    reset_request_api_key,
    set_request_api_key,
)


class ApiKeyContextMiddleware(BaseHTTPMiddleware):
    """Bind the request API key to the request lifetime.

    Works for sync endpoints and SSE StreamingResponse bodies because
    BaseHTTPMiddleware streams the downstream response inside
    ``call_next``, while this context is active.
    """

    async def dispatch(self, request: Request, call_next):
        raw = (request.headers.get(API_KEY_HEADER) or "").strip()
        if len(raw) > 512:
            raw = ""
        token = set_request_api_key(raw or None)
        try:
            return await call_next(request)
        finally:
            reset_request_api_key(token)
