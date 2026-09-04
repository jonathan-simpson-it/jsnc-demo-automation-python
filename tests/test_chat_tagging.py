"""Tests for @-mention (tagged_filenames) retrieval scoping.

The invariant under test: tagging a filename can only narrow a conversation's
scope -- never widen it into another project's documents, and never silently
fall back to the closest in-scope match when the tag doesn't exist in scope.
"""


def _scope_tagged(allowed, tagged):
    from src.api.routes.agents import _scope_tagged as fn

    return fn(allowed, tagged)


def test_no_tags_leaves_scope_untouched():
    assert _scope_tagged(["a.pdf", "b.pdf"], []) == ["a.pdf", "b.pdf"]
    assert _scope_tagged(None, []) is None


def test_tags_narrow_project_scope_to_intersection():
    allowed = ["a.pdf", "b.pdf", "c.pdf"]
    assert _scope_tagged(allowed, ["b.pdf"]) == ["b.pdf"]
    assert _scope_tagged(allowed, ["b.pdf", "a.pdf"]) == ["a.pdf", "b.pdf"]


def test_tag_outside_project_scope_yields_empty_scope():
    """A mention of another project's doc must never leak: empty scope -> the
    agent's explicit no-data path, not a fallback to the closest match."""
    allowed = ["a.pdf", "b.pdf"]
    assert _scope_tagged(allowed, ["other_project.pdf"]) == []


def test_tagged_filenames_alone_scope_a_global_conversation():
    """Global (unscoped) chats restricted by explicit tags only retrieve
    the named files."""
    assert _scope_tagged(None, ["a.pdf", "b.pdf"]) == ["a.pdf", "b.pdf"]
