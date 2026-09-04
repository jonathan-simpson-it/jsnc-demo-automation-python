"""Tests for cross-document entity linking."""

from src.agents.entities import detect_entities, link_entities_across_docs


def test_detect_entities_finds_companies():
    text = "Acme Corp raised $10M. The CEO of Acme Corp is Sarah Chen."
    entities = detect_entities(text)
    names = [e["name"].lower() for e in entities]
    assert any("acme" in n for n in names)


def test_detect_entities_finds_people():
    text = "Sarah Chen leads the team. Jonathan Devano works at Archbridge."
    entities = detect_entities(text)
    names = [e["name"] for e in entities]
    assert "Sarah Chen" in names


def test_link_entities_across_docs():
    docs = {
        "memo.md": "Acme Corp CEO Sarah Chen reported $4M ARR.",
        "term_sheet.md": "Acme Corp Series A with lead investor Archbridge.",
    }
    links = link_entities_across_docs(docs)
    assert "Acme Corp" in links or "acme corp" in [k.lower() for k in links]


def test_empty_text():
    assert detect_entities("") == []
    assert detect_entities("just some random words") == []
