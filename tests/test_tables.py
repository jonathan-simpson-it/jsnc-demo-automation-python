"""Tests for table-aware chunking."""

from src.ingestion.tables import extract_tables_from_text, format_table_as_text


def test_extract_simple_table():
    text = """Company | Revenue | Growth
Acme Corp | $10M | 120%
Beta Inc | $5M | 80%"""
    tables = extract_tables_from_text(text)
    assert len(tables) >= 1
    assert len(tables[0]["headers"]) == 3
    assert "Acme Corp" in tables[0]["rows"][0]


def test_extract_no_table():
    text = "This is just regular paragraph text with no tables."
    tables = extract_tables_from_text(text)
    assert len(tables) == 0


def test_format_table_as_text():
    table = {
        "headers": ["Company", "Revenue"],
        "rows": [["Acme", "$10M"], ["Beta", "$5M"]],
    }
    text = format_table_as_text(table)
    assert "Company" in text
    assert "Revenue" in text
    assert "Acme" in text


def test_table_with_pipe_delimiters():
    text = """Name | Score
Alice | 95
Bob | 87"""
    tables = extract_tables_from_text(text)
    assert len(tables) == 1
    assert tables[0]["headers"] == ["Name", "Score"]
    assert len(tables[0]["rows"]) == 2
