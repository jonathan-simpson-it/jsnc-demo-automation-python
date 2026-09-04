"""Tests for per-project retrieval scoping."""


class _FakeVectorStore:
    """Minimal stand-in recording every search call."""

    def __init__(self, documents: list[dict] | None = None):
        self._documents = documents or []
        self.calls: list[dict] = []

    def list_documents(self) -> list[dict]:
        return self._documents

    def search(self, query, k=4, source_filter=None, filenames=None, **kwargs):
        self.calls.append(
            {"query": query, "k": k, "source_filter": source_filter, "filenames": filenames}
        )
        return []


def _imports():
    from src.tools import search as search_mod
    from config.settings import settings as st

    return search_mod, st


def test_empty_project_scope_tells_agent_there_are_no_documents():
    """A project without documents must not trigger any retrieval."""
    search_mod, _ = _imports()
    store = _FakeVectorStore()
    tool = search_mod.create_search_tool(store, allowed_filenames=[])
    out = tool.invoke("anything at all")
    assert "No documents are assigned to the current project scope" in out
    assert store.calls == []


def test_scope_is_forwarded_to_every_search(monkeypatch):
    """All-collection searches must carry the project's filename scope."""
    search_mod, settings = _imports()
    monkeypatch.setattr(settings, "enable_bm25", False)
    monkeypatch.setattr(settings, "enable_llm_rewrite", False)
    store = _FakeVectorStore()  # no documents -> no detection, all-search path
    tool = search_mod.create_search_tool(store, allowed_filenames=["memo_a.pdf", "term_b.pdf"])
    out = tool.invoke("What is the valuation?")
    assert "No relevant documents found" in out
    assert store.calls, "expected at least one search call"
    for call in store.calls:
        assert call["filenames"] == {"memo_a.pdf", "term_b.pdf"}, call


def test_detection_cannot_pick_documents_outside_scope(monkeypatch):
    """Keyword detection restricted to scoped documents only."""
    search_mod, settings = _imports()
    monkeypatch.setattr(settings, "enable_bm25", False)
    monkeypatch.setattr(settings, "enable_llm_rewrite", False)
    # Only an out-of-scope doc has signals for this query; the scoped corpus
    # is empty, so detection must return None and nothing may be searched
    # outside the scope.
    store = _FakeVectorStore([])
    tool = search_mod.create_search_tool(store, allowed_filenames=[])
    out = tool.invoke("liquidation preference")
    assert "No documents are assigned to the current project scope" in out
    assert store.calls == []

    # A scoped doc with no matching signals must still search inside the scope.
    store2 = _FakeVectorStore([{"filename": "acme_memo.pdf"}])
    tool2 = search_mod.create_search_tool(store2, allowed_filenames=["acme_memo.pdf"])
    out2 = tool2.invoke("What is the valuation?")
    assert "No relevant documents found" in out2
    for call in store2.calls:
        assert call["filenames"] == {"acme_memo.pdf"}
