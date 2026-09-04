"""Dependency injection for FastAPI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.vector_store.chroma import VectorStore

if TYPE_CHECKING:
    from src.agents.router import RouterAgent


_vector_store: VectorStore | None = None
_router_agent: RouterAgent | None = None


def get_vector_store() -> VectorStore:
    """Get the global vector store instance."""
    if _vector_store is None:
        raise RuntimeError("Vector store not initialized")
    return _vector_store


def set_vector_store(store: VectorStore) -> None:
    """Set the global vector store instance."""
    global _vector_store, _router_agent
    _vector_store = store
    _router_agent = None  # Reset cached agent when store changes


def get_router_agent() -> RouterAgent:
    """Get or create the cached RouterAgent singleton.

    Reuses the same instance across requests to avoid creating
    5 ChatDeepSeek LLMs per API call.
    """
    global _router_agent
    if _router_agent is None:
        from src.agents.router import RouterAgent
        _router_agent = RouterAgent(vector_store=get_vector_store())
    return _router_agent
