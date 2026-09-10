"""Middleware that binds a request ID to every request and standardizes 500s.

- Accepts a caller-supplied ``X-Request-ID`` when it looks safe, otherwise
  generates one, and echoes it on the response ``X-Request-ID`` header.
- The ID is available to loggers/audit code via ``request_ctx.get_request_id()``.
- Unhandled exceptions become a JSON error envelope (never a raw traceback)
  and are logged server-side with the request ID attached.
"""

from __future__ import annotations

import re
import time

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.utils.logger import get_logger
from src.utils.request_ctx import (
    get_request_id,
    new_request_id,
    reset_request_id,
    set_request_id,
)

logger = get_logger("api.http")

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Correlate requests end to end via a request ID."""

    async def dispatch(self, request: Request, call_next):
        incoming = (request.headers.get(REQUEST_ID_HEADER) or "").strip()
        request_id = incoming if _SAFE_ID.match(incoming) else new_request_id()
        token = set_request_id(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except HTTPException:
            raise
        except RequestValidationError:
            raise
        except Exception as exc:  # pragma: no cover - defensive catch-all
            logger.exception(
                "unhandled error %s %s",
                request.method,
                request.url.path,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "detail": {
                        "code": "internal_error",
                        "message": "Internal server error",
                        "request_id": request_id,
                    }
                },
                headers={REQUEST_ID_HEADER: request_id},
            )
        finally:
            reset_request_id(token)
        duration_ms = int((time.perf_counter() - start) * 1000)
        response.headers[REQUEST_ID_HEADER] = request_id
        log = logger.warning if response.status_code >= 400 else logger.debug
        log(
            "%s %s %s %sms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
