"""Tests for graph mail demo drafts (offline)."""

from src import graph_mail


def test_demo_draft_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_mail, "configured", lambda: False)
    db = str(tmp_path / "drafts.db")
    created = graph_mail.create_draft(
        "Weekly digest", "## Summary\n\n47 queries.", to=["a@b.c"], db_path=db
    )
    assert created["demo"] is True
    assert created["id"].startswith("demo-draft-")
    drafts = graph_mail.list_drafts(db_path=db)
    assert len(drafts) == 1
    assert drafts[0]["subject"] == "Weekly digest"
    assert drafts[0]["to"] == "a@b.c"
    assert drafts[0]["demo"] is True


def test_demo_drafts_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_mail, "configured", lambda: False)
    db = str(tmp_path / "drafts.db")
    graph_mail.create_draft("first", "one", db_path=db)
    graph_mail.create_draft("second", "two", db_path=db)
    drafts = graph_mail.list_drafts(db_path=db)
    assert [d["subject"] for d in drafts] == ["second", "first"]


def test_create_draft_rejects_bad_content_type(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_mail, "configured", lambda: False)
    db = str(tmp_path / "drafts.db")
    try:
        graph_mail.create_draft("s", "b", content_type="video", db_path=db)
        assert False, "expected ValueError"
    except ValueError:
        pass
