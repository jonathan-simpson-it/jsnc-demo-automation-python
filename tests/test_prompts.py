"""Tests for prompt helpers in src.agents.prompts."""

from src.agents.prompts import clean_citations


def test_strips_citation_tags():
    assert clean_citations("$4M [Source 1: memo.md, page 1, line 5]") == "$4M"
    assert clean_citations("Sarah Chen [Source: cv.pdf, p.1, line 3]") == "Sarah Chen"
    assert clean_citations("[Source 2: memo.md, page 1, line 3]") == ""


def test_cleans_space_left_by_tag_before_period():
    """Regression: tags that sat between a clause and its period leave " ."."""
    text = (
        "The company relies on the subsidy window "
        "[Source 1: polyu-ifc-enosis.pdf, page 1, line 22]."
    )
    assert clean_citations(text) == "The company relies on the subsidy window."


def test_cleans_space_before_period_and_comma_artifacts():
    text = (
        "up to 12 months , creating dependency on public funding . "
        "The seed funding goal is HK$10,000,000 , with 60% allocated ."
    )
    expected = (
        "up to 12 months, creating dependency on public funding. "
        "The seed funding goal is HK$10,000,000, with 60% allocated."
    )
    assert clean_citations(text) == expected


def test_cleans_space_before_punctuation_after_closing_quote():
    text = (
        'the pitch claims "Clinician Behavior Alteration: 0%" , '
        "but growth is aggressive"
    )
    expected = (
        'the pitch claims "Clinician Behavior Alteration: 0%", '
        "but growth is aggressive"
    )
    assert clean_citations(text) == expected

    text2 = 'described as "extremely expensive" . Larger competitors may react'
    expected2 = 'described as "extremely expensive". Larger competitors may react'
    assert clean_citations(text2) == expected2


def test_collapses_whitespace_runs():
    assert clean_citations("line  one\n\nline two   ends") == "line one line two ends"
    assert clean_citations("   padded   ") == "padded"


def test_plain_text_passes_through():
    assert clean_citations("No citations here") == "No citations here"
    assert clean_citations("") == ""
