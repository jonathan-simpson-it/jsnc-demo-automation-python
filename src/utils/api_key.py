"""Request-scoped API key support (bring-your-own-key).

The user's key travels per-request in the ``X-API-Key`` header and lives
only in a contextvar for the duration of one request — it is never
persisted, cached, or logged server-side.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

API_KEY_HEADER = "X-API-Key"
_MAX_HEADER_LENGTH = 512

_request_api_key: ContextVar[str | None] = ContextVar(
    "request_api_key", default=None
)


class ApiKeyMissingError(RuntimeError):
    """Raised when no API key is available (request or settings)."""


def set_request_api_key(key: str | None) -> Token:
    """Store the per-request key (or None) and return the reset token."""
    return _request_api_key.set(key)


def reset_request_api_key(token: Token) -> None:
    """Restore the previous context value."""
    _request_api_key.reset(token)


def get_request_api_key() -> str | None:
    """Return the key set for the current request, if any."""
    return _request_api_key.get()


def resolve_api_key() -> str:
    """Return the request key, else the settings key.

    Raises ApiKeyMissingError when neither is configured.
    """
    from config.settings import settings

    request_key = get_request_api_key()
    if request_key:
        return request_key
    if settings.deepseek_api_key:
        return settings.deepseek_api_key
    raise ApiKeyMissingError(
        "No DeepSeek API key available. Add your key in the app "
        "(header API key button) or set DEEPSEEK_API_KEY on the server."
    )
